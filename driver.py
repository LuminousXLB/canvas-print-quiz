import argparse
import logging
from base64 import b64decode
from io import BytesIO

import questionary
from PyPDF2 import PdfReader
from rich.logging import RichHandler
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
log.formatter = logging.Formatter("%(message)s", datefmt="[%X]")
log.handlers = [RichHandler(rich_tracebacks=True)]


class CanvasDriver:
    def __init__(self, username, password, *, headless=False):
        assert username
        assert password

        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")

        self.web = webdriver.Chrome(options=chrome_options)
        self.web.get("https://canvas.nus.edu.sg")
        self.web.find_element(By.LINK_TEXT, "NUS Students / Alumni").click()
        self.web.find_element(By.ID, "userNameInput").send_keys(username)
        self.web.find_element(By.ID, "passwordInput").send_keys(password)
        self.web.find_element(By.ID, "submitButton").click()


def get_canvas_driver(headless=False):
    username = questionary.text("Canvas username").ask()
    password = questionary.password("Canvas password").ask()
    return CanvasDriver(username, password, headless=headless)


def get_user_from_name(driver, course_id, name):
    driver.web.get(f"https://canvas.nus.edu.sg/courses/{course_id}/users")
    WebDriverWait(driver.web, 10).until(
        lambda drv: drv.find_element(By.LINK_TEXT, name)
    )
    user_link = driver.web.find_element(By.LINK_TEXT, name).get_attribute("href")
    return user_link.split("/")[-1]


def clean_submission_page(driver):
    driver.web.execute_script("$('#questions').removeClass()")
    selectors = [
        "#content > div.quiz-nav.pagination",
        "#content > div.quizzes-speedgrader-padding",
        "#content > div.grade-by-question-warning",
        "#content > header > h2 > a",
        "#update_history_form > div > div.alert",
        "#update_history_form > div > div.quiz_score",
        "#update_history_form > div > div.quiz_duration",
        "div.user_points",
        "div.quiz_comment",
        "div.answer_group",
        "div.eesy.eesy-tab2-container",
        "#speed_update_scores_container",
    ]

    for selector in selectors:
        driver.web.execute_script(f"$('{selector}').remove()")


def set_device_metrics_override(driver, width, height, scale):
    return driver.web.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": scale,
            "mobile": False,
        },
    )


def print_to_pdf(driver, paperWidth, paperHeight):
    return b64decode(
        driver.web.execute_cdp_cmd(
            "Page.printToPDF",
            {
                "paperWidth": paperWidth,
                "paperHeight": paperHeight,
            },
        ).get("data")
    )


def export_one_page_pdf(driver, width, height: int | tuple):
    if isinstance(height, tuple):
        inf, sup = height
        if inf < sup:
            mid = (inf + sup) // 2
            raw = print_to_pdf(driver, width, mid)
            pgs = len(PdfReader(BytesIO(raw)).pages)
            if pgs == 1:
                return export_one_page_pdf(driver, width, (inf, mid))
            else:
                return export_one_page_pdf(driver, width, (mid, sup))
        else:
            height = inf

    raw = print_to_pdf(driver, width, height)
    pgs = len(PdfReader(BytesIO(raw)).pages)
    if pgs == 1:
        return raw
    else:
        return export_one_page_pdf(driver, width, ((pgs - 1) * height, pgs * height))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("course_id", type=int)
    parser.add_argument("quiz_id", type=int)
    parser.add_argument("name")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    course_id = args.course_id
    quiz_id = args.quiz_id
    name = args.name

    driver = get_canvas_driver(headless=True)
    user_id = get_user_from_name(driver, course_id, name)
    log.info(f"User ID: {user_id}")

    url = f"https://canvas.nus.edu.sg/courses/{course_id}/quizzes/{quiz_id}/history?headless=1&user_id={user_id}"
    log.info(f"URL: {url}")
    driver.web.get(url)
    clean_submission_page(driver)
    set_device_metrics_override(driver, 1920, 1080, 1)

    log.info("Exporting PDF...")
    with open(f"{name}.pdf", "wb") as f:
        f.write(export_one_page_pdf(driver, 11, 17))
    log.info(f"Exported to {name}.pdf")

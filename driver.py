import argparse
import json
import logging
from base64 import b64decode
from io import BytesIO
from pathlib import Path

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


def debug_decorator(func):
    def wrapper(*args, **kwargs):
        log.debug(f"Calling {func.__name__} with args={args} and kwargs={kwargs}")
        return func(*args, **kwargs)

    return wrapper


@debug_decorator
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
                if inf == mid:
                    return raw
                else:
                    return export_one_page_pdf(driver, width, (inf, mid))
            else:
                return export_one_page_pdf(driver, width, (mid + 1, sup))
        else:
            height = inf

    raw = print_to_pdf(driver, width, height)
    pgs = len(PdfReader(BytesIO(raw)).pages)
    if pgs == 1:
        return raw
    else:
        return export_one_page_pdf(driver, width, ((pgs - 2) * height, pgs * height))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--json", type=Path, required=False)
    parser.add_argument("--course", dest="course_id", type=int, required=False)
    parser.add_argument("--quiz", dest="quiz_id", type=int, required=False)
    parser.add_argument("--name", dest="name", type=str, required=False)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    config = {}
    if args.json:
        config = json.loads(args.json.read_text())

    course_id = config.get("course_id") or args.course_id
    assert course_id, "Course ID is required"
    log.info(f"Course ID: {course_id}")

    quiz_id = config.get("quiz_id") or args.quiz_id
    assert quiz_id, "Quiz ID is required"
    log.info(f"Quiz ID: {quiz_id}")

    name = config.get("name") or args.name
    assert name, "Name is required"
    log.info(f"Name: {name}")

    username = config.get("username") or questionary.text("Canvas username").ask()
    password = config.get("password") or questionary.password("Canvas password").ask()

    driver = CanvasDriver(username, password, headless=True)

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

import argparse
from string import whitespace
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


def clean_submission_page(driver):
    driver.web.execute_script("$('#questions').removeClass()")
    selectors = [
        "#content > div.grade-by-question-warning",
        "#content > div.quiz-nav.pagination",
        "#content > div.quizzes-speedgrader-padding",
        "#content > header > h2 > a",
        "#speed_update_scores_container",
        "#update_history_form > div > div.alert",
        "#update_history_form > div > div.quiz_duration",
        "#update_history_form > div > div.quiz_score",
        "div.answer_group",
        "div.answers_wrapper",
        "div.eesy.eesy-tab2-container",
        "div.quiz_comment",
        "div.user_points",
        "span.answer_arrow",
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
        return export_one_page_pdf(driver, width, ((pgs - 3) * height, pgs * height))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--json", type=Path, required=False)
    parser.add_argument("--course", dest="course_id", type=int, required=False)
    parser.add_argument("--quiz", dest="quiz_id", type=int, required=False)
    parser.add_argument("--user", dest="user_id", type=int, required=False)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    config = {}
    if args.json:
        config = json.loads(args.json.read_text())

    course_id = args.course_id or config.get("course_id")
    assert course_id, "Course ID is required"
    log.info(f"Course ID: {course_id}")

    quiz_id = args.quiz_id or config.get("quiz_id")
    assert quiz_id, "Quiz ID is required"
    log.info(f"Quiz ID: {quiz_id}")

    user_id = args.user_id or config.get("user_id")
    assert user_id, "User ID is required"
    log.info(f"User ID: {user_id}")

    username = config.get("username") or questionary.text("Canvas username").ask()
    password = config.get("password") or questionary.password("Canvas password").ask()

    driver = CanvasDriver(username, password, headless=True)

    url = f"https://canvas.nus.edu.sg/courses/{course_id}/quizzes/{quiz_id}/history?headless=1&user_id={user_id}"
    log.info(f"URL: {url}")
    driver.web.get(url)
    clean_submission_page(driver)
    set_device_metrics_override(driver, 1920, 1080, 1)

    log.info("Exporting PDF...")

    outfn = Path(
        "".join(filter(lambda c: c not in whitespace, f"{quiz_id}-{user_id:06d}.pdf"))
    )
    with open(outfn, "wb") as f:
        f.write(export_one_page_pdf(driver, 11, 17))
    log.info(f"Exported to {outfn.absolute()}")

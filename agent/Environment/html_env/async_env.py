from typing import Tuple, Any, Union

from playwright.async_api import async_playwright, Page
from playwright.async_api import Error as PlaywrightError
from playwright.sync_api import ViewportSize
from urllib.parse import urlparse, urljoin
from beartype import beartype
from difflib import SequenceMatcher

from PIL import Image
from io import BytesIO
import asyncio
import base64
import re

from .actions import Action, ActionTypes
from .build_tree import HTMLTree
from .utils import stringfy_value
import time

from agent.Prompt import *
from logs import logger
import json
import os
class ActionExecutionError(Exception):
    """Custom action execution exception class"""

    def __init__(self, action_type, message, selector=None):
        self.action_type = action_type
        self.message = message
        self.selector = selector
        super().__init__(message)

class SelectorExecutionError(Exception):
    def __init__(self, message, selector=None):
        super().__init__(message)

class AsyncHTMLEnvironment:
    @beartype
    def __init__(
        self,
        mode="dom",
        max_page_length: int = 8192,
        headless: bool = True,
        slow_mo: int = 0,
        current_viewport_only: bool = False,
        viewport_size: ViewportSize = {"width": 1280, "height": 720},
        save_trace_enabled: bool = False,
        sleep_after_execution: float = 0.0,
        locale: str = "en-US",
        use_vimium_effect=True
    ):
        self.use_vimium_effect = use_vimium_effect
        self.mode = mode
        self.headless = headless
        self.slow_mo = slow_mo
        self.current_viewport_only = current_viewport_only
        self.reset_finished = False
        self.viewport_size = viewport_size
        self.save_trace_enabled = save_trace_enabled
        self.sleep_after_execution = sleep_after_execution
        self.tree = HTMLTree()
        self.locale = locale
        self.context = None
        self.browser = None

    async def page_on_handler(self, page):
        self.page = page

    async def setup(self, start_url: str) -> None:
        self.playwright = await async_playwright().start()
        # Connect to browser using BrowserBase
        logger.info("Browserbase Cloud Environment Start...")
        browser_cdp_url = f"wss://connect.browserbase.com?apiKey={os.environ['BROWSERBASE_API_KEY']}"
        self.browser = await self.playwright.chromium.connect_over_cdp(browser_cdp_url)
        self.context = self.browser.contexts[0]  # Use the existing context from BrowserBase
        self.context.on("page", self.page_on_handler)

        if start_url:
            # Use the first page from the BrowserBase connection
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            await self.page.goto(start_url, timeout=10000)
            await self.page.wait_for_timeout(500)
            self.html_content = await self.page.content()
        else:
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.html_content = await self.page.content()

        # JS event listener
        await self.context.expose_binding(
            "handleEvent",
            lambda source, selector, event_type, element_info: self._handle_event(selector, event_type, element_info)
        )

    async def _event_listener(self):
        """Add universal event listener"""
        logger.info("Setting up event listeners...")  # Add debug log
        try:
            # Then set up event listeners
            await self.page.evaluate("""
                () => {
                    const allEvents = [
                        'click', 'input', 'change', 'keydown', 'keyup',
                        'mouseover', 'mouseout', 'mousedown', 'mouseup', 'focus', 'blur'
                    ];

                    function getElementSelector(element) {
                        if (!element) return null;
                        // Try to get unique selector for the element
                        try {
                            let path = [];
                            while (element && element.nodeType === Node.ELEMENT_NODE) {
                                let selector = element.nodeName.toLowerCase();
                                if (element.id) {
                                    selector += '#' + element.id;
                                    path.unshift(selector);
                                    break;
                                } else {
                                    let sibling = element;
                                    let nth = 1;
                                    while (sibling.previousElementSibling) {
                                        sibling = sibling.previousElementSibling;
                                        if (sibling.nodeName === element.nodeName) nth++;
                                    }
                                    if (nth > 1) selector += `:nth-child(${nth})`;
                                }
                                path.unshift(selector);
                                element = element.parentNode;
                            }
                            return path.join(' > ');
                        } catch (e) {
                            return null;
                        }
                    }

                    function getElementInfo(element) {
                        return {
                            textContent: element.textContent || '',
                            value: element.value || '',
                            tagName: element.tagName.toLowerCase()
                        };
                    }

                    allEvents.forEach(eventType => {
                        document.addEventListener(eventType, (event) => {
                            const element = event.target;
                            const selector = getElementSelector(element);
                            const elementInfo = getElementInfo(element);

                            window.handleEvent(
                                selector,
                                eventType,
                                JSON.stringify(elementInfo)
                            );
                        }, true);
                    });
                }
            """)
            logger.info("Event listeners setup completed")
        except Exception as e:
            logger.error(f"Failed to setup event listeners: {str(e)}")


    async def _handle_event(self,selector, event_type, element_info_str):
        """
        Handle DOM events by updating task events
        """
        def clean_text(text):
            return text.replace("\n", "").replace("\t", "")
        try:
            element_info = json.loads(element_info_str)
            logger.info(f"Event received - selector: {selector}, type: {event_type}, info: {element_info}")
            # Create current event
            current_event = {
                "selector": selector,
                "status": True,
                "target_value": element_info.get("value") or element_info.get("textContent", ""),
                "target_value_clean": clean_text(element_info.get("value") or element_info.get("textContent", "")),
                "event_type": event_type
            }

            directory_path = os.path.join(os.path.dirname(__file__), '..', 'js_event')
            os.makedirs(directory_path, exist_ok=True)  # Ensure the directory exists
            file_path = os.path.join(directory_path, "current_event.json")

            logger.info(f"Saving event to file: {file_path}")

            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as json_file:
                    try:
                        events = json.load(json_file)
                    except json.JSONDecodeError:
                        events = []
            else:
                events = []
            events.append(current_event)
            logger.info("Appended new event to the list.")

            with open(file_path, "w", encoding="utf-8") as json_file:
                json.dump(events, json_file, indent=4, ensure_ascii=False)
                logger.info("Saved updated events to file.")

        except json.JSONDecodeError:
            logger.error(f"Failed to parse element info: {element_info_str}")
        except Exception as e:
            logger.error(f"Error handling event: {str(e)}")

    async def get_obs(self) -> Union[str, Tuple[str, str]]:
        observation = ""
        observation_VforD = ""
        try:
            if not self.html_content.strip():
                self.html_content = await self.retry_content()
            self.tree.fetch_html_content(self.html_content)
            logger.info("-- Successfully fetch html content")
            tab_name = await self.page.title()
            dom_tree = self.tree.build_dom_tree()
            observation = f"current web tab name is \'{tab_name}\'\n" + dom_tree
            if self.mode in ["d_v", "dom_v_desc", "vision_to_dom"]:
                observation_VforD = await self.capture()
        except Exception as e:
            logger.error(f"-- Failed to fetch html content,error occur {e}")
        if self.mode in ["d_v", "dom_v_desc", "vision_to_dom"]:
            is_valid, message = is_valid_base64(
                observation_VforD)
            logger.info(
                "Successfully fetch html content with observation_VforD:", message)
        return (observation, observation_VforD) if self.mode in ["d_v", "dom_v_desc", "vision_to_dom"] else observation

    async def reset(self, start_url: str = ""):
        await self.setup(start_url)

    async def click(self, action):
        try:
            label, element_id = self.tree.get_tag_name(
                self.tree.elementNodes[action["element_id"]])
            action.update({"element_id": element_id,
                           "element_name": label})
            selector, xpath = self.tree.get_selector_and_xpath(
                action["element_id"])
        except Exception as e:
            logger.error(
                f"selector:{selector},label_name:{label},element_id: {element_id},error ({e}) in click action.")
        if label == "link":
            try:
                element = self.tree.elementNodes[element_id]
                url = element["attributes"].get("href")
                if bool(urlparse(url).netloc) is False:
                    base_url = self.page.url()
                    url = urljoin(base_url, url)
                # self.last_page = self.page
                # self.page = await self.context.new_page()
                await self.page.goto(url, timeout=10000)
                await self.page.wait_for_timeout(2000)
                self.html_content = await self.page.content()
            except:
                try:
                    # self.last_page = self.page
                    selector = rf"{selector}"
                    await self.page.evaluate(f'''(selector) => {{
                        var element = document.querySelector(selector);
                        if (element) {{
                            element.click();   
                        }} 
                    }}''', selector)
                    self.html_content = await self.page.content()
                except Exception as e:
                    raise e
        else:
            try:
                try:
                    await self.page.locator(selector).click()
                except:
                    selector = rf"{selector}"
                    await self.page.evaluate(f'''(selector) => {{
                        var element = document.querySelector(selector);
                        if (element) {{
                            element.click();   
                        }} 
                    }}''', selector)
                await self.page.wait_for_timeout(1000)
                self.html_content = await self.page.content()
            except Exception as e:
                raise e

    async def goto(self, action):
        await self.load_page_with_retry(action['url'])
        self.html_content = await self.page.content()

    async def fill_search(self, action):
        try:
            label, element_id = self.tree.get_tag_name(
                self.tree.elementNodes[action["element_id"]])
            action.update({"element_id": element_id,
                           "element_name": label})
            selector, xpath = self.tree.get_selector_and_xpath(
                action["element_id"])
        except Exception as e:
            logger.error(
                f"selector:{selector},label_name:{label},element_id: {element_id},error ({e}) in fill_search action.")
        try:
            value = stringfy_value(action['fill_text'])
            await self.page.locator(selector).fill(value)
            await self.page.locator(selector).press("Enter")
            self.html_content = await self.page.content()
        except:
            try:
                selector = rf"{selector}"
                value = stringfy_value(action['fill_text'])
                await self.page.evaluate(f'''
                    (selector) => {{
                        var element = document.querySelector(selector);
                        if (element) {{
                            element.value = '{value}';
                            element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            element.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter' }}));
                        }}
                    }}
                ''', selector)
                self.html_content = await self.page.content()
            except Exception as e:
                raise e

    async def fill_form(self, action):
        try:
            label, element_id = self.tree.get_tag_name(
                self.tree.elementNodes[action["element_id"]])
            action.update({"element_id": element_id,
                           "element_name": label})
            selector, xpath = self.tree.get_selector_and_xpath(
                action["element_id"])
        except Exception as e:
            logger.error(
                f"selector:{selector},label_name:{label},element_id: {element_id},error ({e}) in fill_form action.")
        try:
            value = stringfy_value(action['fill_text'])
            await self.page.locator(selector).fill(value)
            self.html_content = await self.page.content()
        except:
            try:
                selector = rf"{selector}"
                value = stringfy_value(action['fill_text'])
                await self.page.evaluate(f'''(selector) => {{
                        var element = document.querySelector(selector);
                        if (element) {{
                            element.value = '{value}';
                            element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        }}
                    }}
                ''', selector)
                self.html_content = await self.page.content()
            except Exception as e:
                raise e

    async def search(self, action):
        await self.page.goto("https://www.google.com/search?q="+action["fill_text"], timeout=30000)
        await self.page.wait_for_timeout(2000)
        self.html_content = await self.page.content()

    async def go_back_last_page(self, action):
        # self.page = self.last_page
        # self.last_page = self.page
        await self.page.go_back()
        await self.page.wait_for_timeout(2000)
        self.html_content = await self.page.content()

    async def select_option(self, action):
        try:
            label, element_id = self.tree.get_tag_name(
                self.tree.elementNodes[action["element_id"]])
            action.update({"element_id": element_id,
                           "element_name": label})
            selector, xpath = self.tree.get_selector_and_xpath(
                action["element_id"])
        except Exception as e:
            logger.error(
                f"selector:{selector},label_name:{label},element_id: {element_id},error ({e}) in select_option action.")
        try:
            selector = rf"{selector}"
            optgroup_values = await self.page.evaluate(f'''(selector) => {{
                var values = [];
                var selectElement = document.querySelector(selector);
                var options = selectElement.querySelectorAll('option');
                for (var option of options) {{
                    values.push(option.innerText);
                }}
                var optgroups = selectElement.querySelectorAll('optgroup');
                for (var optgroup of optgroups) {{
                    var options = optgroup.querySelectorAll('option');
                    for (var option of options) {{
                        values.push(option.innerText);
                    }}   
                }}
                return values;
            }}''', selector)
            best_option = [-1, "", -1]
            for i, option in enumerate(optgroup_values):
                similarity = SequenceMatcher(
                    None, option, action['fill_text']).ratio()
                if similarity > best_option[2]:
                    best_option = [i, option, similarity]
            await self.page.evaluate(f'''(selector) => {{
                var selectElement = document.querySelector(selector);
                var options = selectElement.querySelectorAll('option');
                for (var option of options) {{
                    if (option.innerText === "{best_option[1]}") {{
                        option.selected = true;
                        selectElement.dispatchEvent(new Event('change'));
                        return;
                    }}
                }}
                var optgroups = selectElement.querySelectorAll('optgroup');
                for (var optgroup of optgroups) {{
                    var options = optgroup.querySelectorAll('option');
                    for (var option of options) {{
                        if (option.innerText === "{best_option[1]}") {{
                            option.selected = true;
                            selectElement.dispatchEvent(new Event('change'));
                            return;
                        }}
                    }}
                }}
            }}''', selector)
            await self.page.wait_for_timeout(2000)
            self.html_content = await self.page.content()
        except Exception as e:
            raise e

    async def hover(self, action):
        try:
            label, element_id = self.tree.get_tag_name(
                self.tree.elementNodes[action["element_id"]])
            action.update({"element_id": element_id,
                           "element_name": label})
            selector, xpath = self.tree.get_selector_and_xpath(
                action["element_id"])
        except Exception as e:
            logger.error(
                f"selector:{selector},label_name:{label},element_id: {element_id},error ({e}) in hover action.")
        try:
            await self.page.hover(selector)
            self.html_content = await self.page.content()
        except:
            hover = '''() => {
                        var element = document.querySelector('%s');
                        if (element) {
                            element.dispatchEvent(new Event('mouseover', { bubbles: true }));
                        }
                    }
                ''' % selector
            await self.page.evaluate(hover)
            self.html_content = await self.page.content()

    async def scroll_down(self):
        try:
            total_height = await self.page.evaluate("document.body.scrollHeight")
            viewport_height = await self.page.evaluate("window.innerHeight")
            if total_height < viewport_height:
                await self.page.evaluate("window.scrollBy(0, 500)")
                self.html_content = await self.page.content()
            current_scroll = await self.page.evaluate("window.pageYOffset")
            remaining_height = total_height - current_scroll - viewport_height
            if remaining_height <= viewport_height:
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                scroll_amount = current_scroll + viewport_height * 0.75
                await self.page.evaluate(f"window.scrollTo(0, {scroll_amount})")
            self.html_content = await self.page.content()
        except:
            await self.page.mouse.wheel(0, 100)
            self.html_content = await self.page.content()

    async def scroll_up(self):
        try:
            viewport_height = await self.page.evaluate("window.innerHeight")
            current_scroll = await self.page.evaluate("window.pageYOffset")
            if current_scroll > 0:
                if current_scroll < viewport_height:
                    scroll_amount = 0
                else:
                    scroll_amount = current_scroll - viewport_height / 2
                await self.page.evaluate(f"window.scrollTo(0, {scroll_amount})")
            self.html_content = await self.page.content()
        except:
            await self.page.mouse.wheel(0, -100)
            self.html_content = await self.page.content()

    async def execute_action(self, action: Action) -> Union[str, Tuple[str, str]]:
        """
        """
        await self._event_listener()
        if "element_id" in action and action["element_id"] != 0:
            # logger.info(f'action["element_id"]:{action["element_id"]}')
            # logger.info(
            #     f'tree.nodeDict[action["element_id"]]:{self.tree.nodeDict[action["element_id"]]}')
            action["element_id"] = self.tree.nodeDict[action["element_id"]]
            element_value = self.tree.get_element_value(action["element_id"])
        match action["action_type"]:
            case ActionTypes.CLICK:
                try:
                    await self.click(action)
                except Exception as e:
                    error_message = f"Failed to execute click [{action['element_id']}, {element_value}] action. An error({e}) occur"
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.GOTO:
                try:
                    await self.goto(action)
                except Exception as e:
                    error_message = f"Failed to execute goto [{action['url']}] action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.FILL_SEARCH:
                try:
                    await self.fill_search(action)
                except Exception as e:
                    error_message = f"Failed to execute fill_form [{action['element_id']},{action['fill_text']}] action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.FILL_FORM:
                try:
                    await self.fill_form(action)
                except Exception as e:
                    error_message = f"Failed to execute fill_form [{action['element_id']},{action['fill_text']}] action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.GOOGLE_SEARCH:
                try:
                    await self.search(action)
                except Exception as e:
                    error_message = f"Failed to execute google_search[{action['fill_text']}] action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.GO_BACK:
                try:
                    await self.go_back_last_page(action)
                except Exception as e:
                    error_message = f"Failed to execute go_back action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.SELECT_OPTION:
                try:
                    await self.select_option(action)
                except Exception as e:
                    error_message = f"Failed to execute select_option [{action['element_id']},{action['fill_text']}] action. An error({e}) occur."
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.HOVER:
                try:
                    await self.hover(action)
                except Exception as e:
                    error_message = f"Failed to execute hover [{action['element_id']},{element_value}] action. An error({e}) occur"
                    # print(error_message)
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.SCROLL_DOWN:
                try:
                    await self.scroll_down()
                except Exception as e:
                    error_message = f"Failed to execute scroll_down action. An error({e}) occur"
                    # print(error_message)
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.SCROLL_UP:
                try:
                    await self.scroll_up()
                except Exception as e:
                    error_message = f"Failed to execute scroll_up action. An error({e}) occur"
                    # print(error_message)
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.NONE:
                try:
                    self.html_content = await self.page.content()
                except Exception as e:
                    error_message = f"An error({e}) occur"
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.CACHE_DATA:
                try:
                    self.html_content = await self.page.content()
                except Exception as e:
                    error_message = f"An error({e}) occur"
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case ActionTypes.GET_FINAL_ANSWER:
                try:
                    self.html_content = await self.page.content()
                except Exception as e:
                    error_message = f"An error({e}) occur"
                    raise ActionExecutionError(
                        action['action_type'], error_message) from e
            case _:
                raise ValueError(
                    f"Unknown action type {action['action_type']}"
                )
    async def get_page(self, element_id: int) -> Tuple[Page, str]:
        try:
            selector = self.tree.get_selector(element_id)
        except:
            selector = ""
        return self.page, selector

    async def close(self):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    @staticmethod
    def encode_and_resize(image):
        img_res = 1080
        w, h = image.size
        img_res_h = int(img_res * h / w)
        image = image.resize((img_res, img_res_h))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return encoded_image

    async def capture(self) -> Image:
        if not self.page:
            raise ValueError("Page not initialized or loaded.")
        screenshot_bytes = ""
        for i in range(6):
            try:
                screenshot_bytes = await self.page.screenshot()
                break
            except:
                logger.info(
                    "Capture screenshot_bytes failed for", i+1, "times")
                await asyncio.sleep(1)
        screenshot = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
        encoded_screenshot = self.encode_and_resize(screenshot)
        is_valid, message = is_valid_base64(
            encoded_screenshot)
        return encoded_screenshot

    @staticmethod
    async def is_valid_element(page: Page, selector: str):
        element = await page.query_selector(selector)
        if element:
            if await element.is_visible() is False:
                return False
            elif await element.is_hidden() is True:
                return False
        else:
            return False
        return True

    async def load_page_with_retry(self, url, retries=3, delay=5):
        for attempt in range(retries):
            try:
                await self.page.goto(url, timeout=20000)
                await self.page.wait_for_timeout(2000)
                return
            except Exception as e:
                if "Timeout" in str(e):
                    if attempt < retries - 1:
                        logger.info(
                            f"Timeout occurred, retrying in {delay * attempt} seconds...")
                        await asyncio.sleep(delay * (attempt + 1))
                    else:
                        logger.error(
                            f"Max retries {retries} reached, giving up.")
                        raise

    async def retry_content(self, max_retries=3):
        retry_count = 0
        while retry_count < max_retries:
            try:
                await self.page.reload()
                await self.page.wait_for_timeout(3000)
                content = await self.page.content()
                if not content.strip():
                    raise ValueError("Page content is empty")
                return content
            except PlaywrightError as e:
                logger.error(
                    f"Page load timed out or encountered an error, retrying ({retry_count + 1}/{max_retries}): {e}")
                retry_count += 1
        logger.info("Maximum retries reached, unable to load the page.")

    async def test_click_action(self, selector):
        await self.page.wait_for_selector(selector)
        is_clickable = await self.page.is_enabled(selector)
        selector = rf"{selector}"
        try:
            await self.page.evaluate(f'''(selector) => {{
                var element = document.querySelector(selector);
                if (element) {{
                    element.click();   
                }} 
            }}''', selector)
            logger.info("Click Success")
        except Exception as e:
            logger.info("Click Failed:", e)
        await self.page.wait_for_timeout(20000)

    async def test_select_option_action(self, selector, value):
        optgroup_values = await self.page.evaluate(f'''(selector) => {{
                var values = [];
                var selectElement = document.querySelector(selector);
                var options = selectElement.querySelectorAll('option');
                for (var option of options) {{
                    values.push(option.innerText);
                }}
                var optgroups = selectElement.querySelectorAll('optgroup');
                for (var optgroup of optgroups) {{
                    var options = optgroup.querySelectorAll('option');
                    for (var option of options) {{
                        values.push(option.innerText);
                    }}   
                }}
                return values;
            }}''', selector)
        best_option = [-1, "", -1]
        for i, option in enumerate(optgroup_values):
            similarity = SequenceMatcher(None, option, value).ratio()
            if similarity > best_option[2]:
                best_option = [i, option, similarity]
        await self.page.evaluate(f'''(selector) => {{
            var selectElement = document.querySelector(selector);
            var options = selectElement.querySelectorAll('option');
            for (var option of options) {{
                if (option.innerText === "{best_option[1]}") {{
                    option.selected = true;
                    selectElement.dispatchEvent(new Event('change'));
                    return;
                }}
            }}
            var optgroups = selectElement.querySelectorAll('optgroup');
            for (var optgroup of optgroups) {{
                var options = optgroup.querySelectorAll('option');
                for (var option of options) {{
                    if (option.innerText === "{best_option[1]}") {{
                        option.selected = true;
                        selectElement.dispatchEvent(new Event('change'));
                        return;
                    }}
                }}
            }}
        }}''', selector)
        await self.page.wait_for_timeout(2000)

    async def test_fill_form_action(self, selector, value):
        selector = rf"{selector}"
        await self.page.evaluate(f'''(selector) => {{
                var element = document.querySelector(selector);
                if (element) {{
                    element.value = '{value}';
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            }}
        ''', selector)
        await self.page.wait_for_timeout(2000)
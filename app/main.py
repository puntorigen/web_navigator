from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
import instructor, os, json, base64
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from python_ghost_cursor.playwright_async import create_cursor
#from playwright.sync_api import sync_playwright 
from .schemas import ExtractedTask, UserPrompt, NextStepCommand, HealingCommand
from .js_highligher import highlight_js
from PIL import Image
import io, logging, textwrap, sys, random, datetime

load_dotenv()  # Load environment variables

client = instructor.apatch(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))
app = FastAPI()

# replace playwright page.click with ghost cursor click
class GhostPage:
    def __init__(self, page):
        self.page = page
        self.cursor = create_cursor(page)

    async def click(self, selector, **kwargs):
        # Override the click method to use the cursor click
        await self.cursor.click(selector, **kwargs)

    # Delegate other methods to the underlying page object
    def __getattr__(self, name):
        return getattr(self.page, name)
    
# Add middleware to catch and log exceptions
@app.middleware("http")
async def log_exceptions(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logging.error(f"Exception: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"message": "Internal Server Error"}
        )
def extract_task_from_prompt(prompt: str):
    user_prompt = f"""Extract the URL and the task from the following prompt: {prompt}"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_prompt}],
        response_model=ExtractedTask,
        temperature=0.1
    )
    return response

async def init_browser(base_url: str = ""):
    userAgents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.2227.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.3497.92 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    ]
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=False,
        args=["--disable-web-security","--ignore-certificate-errors","--allow-external-pages"] #,"--disable-infobars"]
    )
    #context = await browser.new_context()
    agent = userAgents[random.randint(0, len(userAgents) - 1)]
    print(f"Choosen User Agent: {agent}")
    context = await browser.new_context(
        ignore_https_errors=True,
        #user_agent=userAgents[random.randint(0, len(userAgents) - 1)],
        viewport={"width": 1600, "height": 800},  # Smaller viewport size
        geolocation={"longitude": 41.890221, "latitude": 12.492348},
        permissions=["geolocation"]
    )
    # add init script
    #await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = await context.new_page()
    #page = GhostPage(page)
    #await stealth_async(page)
    return browser, page

def fix_url(url: str):
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    return url

async def navigate_to_url(page, url: str):
    try:
        # Validate URL format (simple check)
        url = fix_url(url)
        # Navigate to the URL with a timeout of 30 seconds
        response = await page.goto(url, timeout=30000) #, wait_until='networkidle'
        # delay for 2 seconds
        await page.wait_for_timeout(2000)

        # Check if the navigation was successful
        if response is None or response.status != 200:
            raise HTTPException(status_code=500, detail=f"Failed to navigate to {url}. Status code: {response.status if response else 'None'}")
        
    except Exception as e:
        logging.error(f"Failed to navigate to URL {url}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to navigate to URL {url}: {str(e)}")

async def run_playwright_script_or_command(page, command_or_script: str, state):
    """
    Helper method to execute a Playwright command or script.
    """
    exec_globals = {"page": page, "state": state}
    exec_locals = {}
    
    # Redirect stdout to capture print statements
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output
    
    try:
        if 'await' in command_or_script or '\n' in command_or_script:
            # Dynamically create an async function to execute the command or script
            async def async_wrapper():
                exec_globals = {"page": page, "state": state}
                exec_locals = {}
                try:
                    exec(f"async def _async_exec_func():\n{textwrap.indent(command_or_script, '    ')}", exec_globals, exec_locals)
                    result = await exec_locals["_async_exec_func"]()
                    
                    # Await any coroutine in the 'results' variable before returning it
                    if 'results' in exec_locals and isinstance(exec_locals['results'], (type(async_wrapper),)):
                        exec_locals['results'] = await exec_locals['results']
                    return exec_locals.get('results', None)
                except Exception as e:
                    raise e

            result = await async_wrapper()
        else:
            # If it's a single command, remove 'await' and evaluate it
            command_to_execute = command_or_script.replace('await ', '').strip()
            result = await eval(command_to_execute)
            
            # If the command returns data, store it in the state
            if result is not None:
                state['last_output'] = result

        # Capture the print output, if any
        output = redirected_output.getvalue()
        if output:
            state['last_output'] = output.strip()
            print(f"Captured output: {output.strip()}")

    except Exception as e:
        logging.error(f"Failed to execute Playwright command/script: {str(e)}", exc_info=True)
        raise e
    
    finally:
        # Reset stdout
        sys.stdout = old_stdout
        redirected_output.close()

    return result 

async def execute_playwright_command(page, command: str, client, state, main_task, screenshot, clean_screenshot, what_do_you_plan_to_do:str='', max_retries=4):
    failed_attempts = []

    try:
        # Try to execute the original command or script using the helper method
        result = await run_playwright_script_or_command(page, command, state)
         # Record the command as successful
        state['steps'].append({
            "command": command,
            "status": "success",
            "reason": what_do_you_plan_to_do,
            "output": result.strip() if result else None
        })
        return result

    except Exception as e:
        logging.error(f"Failed to execute Playwright command: {str(e)}", exc_info=True)
        
        # Append the failure context to failed_attempts
        failed_attempts.append({
            "attempt": 1,
            "command": command,
            "error": str(e)
        })

        # Enter the retry loop within the exception handling block
        retry_count = 1  # We already made one attempt with the original command

        while retry_count <= max_retries:
            try:
                # Attempt to heal the command or script
                healed_command_or_script = await request_healed_command(client, state, main_task, screenshot, clean_screenshot, failed_attempts)
                
                # Check if the healed command is the same as the original command
                if healed_command_or_script.command == command:
                    logging.warning(f"Healed command is the same as the original command: {command}. Skipping re-execution.")
                    break  # Exit the retry loop if healing is ineffective
                if healed_command_or_script.output:
                    # Record the healed command or script as successful
                    state['steps'].append({
                        "command": healed_command_or_script.command,
                        "status": "healed_vision",
                        "reason": healed_command_or_script.reason_for_fix,
                        "output": healed_command_or_script.output.strip()
                    })
                    return healed_command_or_script.output
                
                # Execute the healed command or script using the helper method
                result = await run_playwright_script_or_command(page, healed_command_or_script.command, state)

                # Record the healed command or script as successful
                state['steps'].append({
                    "command": healed_command_or_script.command,
                    "status": "healed",
                    "reason": healed_command_or_script.reason_for_fix,
                    "output": result.strip() if result else None
                })

                return result

            except Exception as healed_exception:
                logging.error(f"Failed to execute healed Playwright command: {str(healed_exception)} on attempt {retry_count + 1}/{max_retries}", exc_info=True)
                
                # Append this failure context to failed_attempts
                failed_attempts.append({
                    "attempt": retry_count + 1,
                    "command": healed_command_or_script.command,
                    "error": str(healed_exception)
                })
                retry_count += 1
        
        # If maximum retries reached, raise the final exception
        raise HTTPException(status_code=500, detail=f"Failed to execute healed Playwright commands after {max_retries} attempts.")

async def perform_task(page, client, main_task, state):
    last_screenshot = state["screenshot"]
    last_clean_screenshot = state["clean_screenshot"]
    print(f"Initial state captured")
    
    while True:
        # Request the next Playwright command from the LLM
        print(f"Requesting next step as command")
        next_command = await request_next_step_as_command(client, state, main_task, last_screenshot, last_clean_screenshot)
        print(f"Received next command: {next_command}")
        if next_command.output:
            print(f"Task step answered directly using vision, with output: {next_command.output}")
            state['steps'].append({
                "command": None,
                "status": "success",
                "reason": next_command.what_do_you_plan_to_do,
                "output": next_command.output.strip()
            })
        else:
            # Execute the Playwright command
            print(f"Executing Playwright command: {next_command.command}")
            await execute_playwright_command(page, next_command.command, client, state, main_task, last_screenshot, last_clean_screenshot, next_command.what_do_you_plan_to_do)

        # Update state with new screenshot, source code, and executed command
        print(f"Updating state with new screenshot and source code")
        clean_screenshot, screenshot_data_url, source_code = await capture_screenshot_and_source(page, f"step-{len(state['steps']) + 1}")
        last_screenshot = screenshot_data_url
        last_clean_screenshot = clean_screenshot
        state["source_code"] = source_code
        print(f"State updated. Next command: {next_command.command}")

        # Check if the task is completed after the command has been executed
        if next_command.task_completed:
            break
    
    # Task is completed
    # Print the final state
    print(f"********** Task completed **********")
    # delete big values for debugging
    del state["screenshot"]
    del state["clean_screenshot"]
    del state["source_code"]
    print(f"Task completed. Final state: {json.dumps(state, indent=2)}")
 
async def capture_screenshot_and_source(page, step: str):
    # Capture a screenshot as JPG (without the highlights first)
    print(f"Capturing CLEAN screenshot for step {step}")
    screenshot_buffer0 = await page.screenshot(full_page=True, type="jpeg", quality=60)

    # Highlight elements on the page
    print(f"Highlighting elements on the page for step {step}")
    await page.evaluate(highlight_js)

    # Capture the screenshot as JPG
    print(f"Capturing screenshot for step {step}")
    screenshot_buffer = await page.screenshot(full_page=True, type="jpeg", quality=80)
    
    print(f"Screenshot captured for step {step}")
    # Convert the JPG image to a base64 data URL
    print(f"Converting screenshot to base64 data URL")
    #screenshot_data_url = f"data:image/jpeg;base64,{base64.b64encode(screenshot_buffer.getvalue()).decode('utf-8')}"
    screenshot_data_url0 = f"data:image/jpeg;base64,{base64.b64encode(screenshot_buffer0).decode('utf-8')}"
    screenshot_data_url = f"data:image/jpeg;base64,{base64.b64encode(screenshot_buffer).decode('utf-8')}"

    # Capture the source code
    source_code = await page.content()

    return screenshot_data_url0, screenshot_data_url, source_code

async def capture_initial_screenshot(page):
    screenshot_clean, screenshot_data_url, source = await capture_screenshot_and_source(page, "initial")
    return screenshot_clean, screenshot_data_url

def read_playwright_reference():
    current_dir = os.path.dirname(os.path.abspath(__file__))  # Get the directory of the current file
    file_path = os.path.join(current_dir, "playwright_ref.md")  # Construct the full path to the markdown file
    
    try:
        with open(file_path, "r") as file:
            return file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"The file {file_path} was not found.")
    except Exception as e:
        raise RuntimeError(f"An error occurred while reading {file_path}: {str(e)}")

async def request_healed_command(client, state, main_task, screenshot, clean_screenshot, failed_attempts):
    # Read the content of the playwright_ref.md file
    playwright_reference = read_playwright_reference()
    
    # Create a string summarizing all failed attempts
    failed_attempts_info = "\n".join([f"Attempt {attempt['attempt']}: Command `{attempt['command']}` failed with error: {attempt['error']}" for attempt in failed_attempts])

    # Get the current date and time
    current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Add source code to the prompt if there are more than two failed attempts
    # Include the source code in the prompt if more than 2 attempts have failed
    source_code_info = ""
    if len(failed_attempts) > 1:
        page_source_code = state.get('source_code', '')
        if page_source_code:
            source_code_info = f"\n# The current page source code is as follows:\n```html\n{page_source_code}\n```\n"

    prompt2 = f"""
# You are a professional automation quality engineer.
# The current date and time is: {current_datetime}.
# You read requirement and write Playwright in Python to automate the test.

The following attempts to execute the command failed:
{failed_attempts_info}

{source_code_info}

Please provide a new Playwright script or command that:
1. Avoids searching for elements based on long text sentences as these are unlikely to be found reliably. Instead, focus on using CSS selectors, ID attributes, or short, stable text fragments.
2. Prioritizes the use of CSS class or ID selectors, which are more reliable for locating elements. If necessary, you may use item numbers (like nth-child selectors) or short and unique text fragments to locate elements.
3. Completes the task within a maximum of 20 steps, avoiding repetitive approaches or actions. If an approach fails, try a different strategy instead of repeating the same action consecutively.

Please provide a new Playwright script or command that accounts for visibility issues, ensuring that elements are present, visible, and interactable before attempting actions. A screenshot of the current state is provided, and the elements are highlighted. 

# Important:
- Always use the asynchronous version of Playwright commands, prefixed with 'await'.
- Before attempting to wait for or interact with an element, first check if the element exists using `page.query_selector()`. Only proceed if the element exists.
- If the element does not exist, log an appropriate message and skip the interaction.
- If you need to assign data to a variable, always assign it to the variable `results`.
- Ensure that assignments are done on a single line and avoid including print statements on the same line as an assignment.
- Do not create multiline assignments or concatenate multiple statements on the same line.
- After assigning data to `results`, use a separate `print(results)` statement on the following line to output the data.
- Avoid chaining operations directly on coroutine results; always await the coroutine first, assign the result to `results`, and then process it separately.

# Use the following reference for Playwright commands as a guide:
```playwright commands reference
{playwright_reference}
```

# Requirement:
`{main_task}`

# Here are the steps taken so far: 
`{json.dumps(state['steps'], indent=2)}`

# Avoid using complex constructs like async functions. Prefer returning a sequence of Playwright commands that can be executed directly, one after another.
    """
    print(f"Healing Prompt: {prompt2}")
    
    user_contents = [
        {"type": "text", "text": prompt2 },
        {
            "type": "image_url", 
            "image_url": {
                "url": clean_screenshot
            }
        },
        {
            "type": "image_url", 
            "image_url": {
                "url": screenshot
            }
        }
    ]
    print(f"Requesting healing command")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": user_contents }
        ],
        response_model=HealingCommand,
        temperature=0.2
    )
    print(f"Healeed Response:",response)
    return response
    #return response['choices'][0]['text'].strip()

async def request_next_step_as_command(client, state, main_task, screenshot, clean_screenshot):
    # Read the content of the playwright_ref.md file
    playwright_reference = read_playwright_reference()
    
    # Determine if the last output was an actionable item
    if 'last_output' in state and isinstance(state['last_output'], list) and len(state['last_output']) > 0:
        action_prompt = "# Based on the output, take the necessary action to proceed with the task."
    else:
        action_prompt = "# Proceed with the next step in the task."

    # Include the last output in the prompt if it exists
    last_output_info = f"\n# The last command produced the following output: {state['last_output']}\n" if 'last_output' in state else ""

    # Get the current date and time
    current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prompt2 = f"""
# You are a professional automation quality engineer.
# The current date and time is: {current_datetime}.
# You read requirement and write Playwright in Python to automate the test.

You write one Playwright command at a time, using the asynchronous version of Playwright commands prefixed with 'await'. A screenshot will be provided after executing that command.
Each element will be highlighted with a black box and its id, class attributes.
For other elements, prefer text-based selector like await page.click("text='Button text'") to improve the stability of the script.
Some website uses custom date or number picker, you should trigger the custom picker then click the buttons instead of filling textual value directly.
You write one Playwright command at a time.

Please provide a new Playwright script or command that:
1. Avoids searching for elements based on long text sentences as these are unlikely to be found reliably. Instead, focus on using CSS selectors, ID attributes, or short, stable text fragments.
2. Prioritizes the use of CSS class or ID selectors, which are more reliable for locating elements. If necessary, you may use item numbers (like nth-child selectors) or short and unique text fragments to locate elements.
3. Completes the task within a maximum of 20 steps, avoiding repetitive approaches or actions. If an approach fails, try a different strategy instead of repeating the same action consecutively.

Please provide a new Playwright script or command that accounts for visibility issues, ensuring that elements are present, visible, and interactable before attempting actions. A screenshot of the current state is provided, and the elements are highlighted. 

# Important:
- Always use the asynchronous version of Playwright commands, prefixed with 'await'.
- Before attempting to wait for or interact with an element, first check if the element exists using `page.query_selector()`. Only proceed if the element exists.
- If the element does not exist, log an appropriate message and skip the interaction.
- If you need to assign data to a variable, always assign it to the variable `results`.
- Ensure that assignments are done on a single line and avoid including print statements on the same line as an assignment.
- Do not create multiline assignments or concatenate multiple statements on the same line.
- After assigning data to `results`, use a separate `print(results)` statement on the following line to output the data.
- Avoid chaining operations directly on coroutine results; always await the coroutine first, assign the result to `results`, and then process it separately.

# Use the following reference for Playwright commands as a guide to complete the task:
```playwright commands reference
{playwright_reference}
```

# Requirement:
`{main_task}`

{last_output_info}

{action_prompt}

# Here are the steps taken so far: 
`{json.dumps(state['steps'], indent=2)}`

# Avoid using complex constructs like async functions. Prefer returning a sequence of Playwright commands that can be executed directly, one after another.
    """
    print(f"Prompt:",prompt2)
    
    user_contents = [
        {"type": "text", "text": prompt2 },
        {
            "type": "image_url", 
            "image_url": {
                #"url": state['screenshot']
                "url": clean_screenshot
            }
        },
        {
            "type": "image_url", 
            "image_url": {
                #"url": state['screenshot']
                "url": screenshot
            }
        }
    ]
    #print(f"user_contents:",user_contents)
    print(f"Requesting next step as command")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": user_contents }
        ],
        response_model=NextStepCommand,
        temperature=0.05
    )
    print(f"Response:",response)
    return response
    #return response['choices'][0]['text'].strip()

async def close_browser(browser):
    await browser.close()

@app.post("/navigate")
async def navigate(user_prompt: UserPrompt):
    extracted_task = extract_task_from_prompt(user_prompt.prompt)
    print(f"Extracted task: {extracted_task}")
    browser, page = await init_browser(extracted_task.url)
    print(f"Browser and page initialized")

    # Initialize the state to track steps
    state = {
        "steps": []
    }

    try:
        # Navigate to the extracted URL
        print(f"Extracted URL: {extracted_task.url}")
        await navigate_to_url(page, extracted_task.url)
        
        # Record the URL navigation as the first step
        state['steps'].append({ 
            "command": f"await page.goto('{extracted_task.url}', timeout=30000, wait_until='networkidle')", #, wait_until='networkidle'
            "status": "success",
            "reason": "Initial navigation to the extracted URL"
        })
        # Get the first screenshot
        clean, high = await capture_initial_screenshot(page)
        state["screenshot"] = high
        state["clean_screenshot"] = clean

        # Perform the task
        print(f"Performing task: {extracted_task.task}")
        await perform_task(page, client, extracted_task.task, state)
        print(f"Task completed successfully")

        return {"message": "Task completed successfully", "state":state}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to perform task: {str(e)}")

    finally:
        await close_browser(browser)
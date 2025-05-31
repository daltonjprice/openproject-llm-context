# OpenProject Task Context Enhancer with Ollama

This Python script automates the process of enriching tasks (work packages) across **all accessible projects** in an OpenProject instance. It generates additional context using a locally running Ollama Large Language Model (LLM), and this context is added as a comment to the respective task.

The script utilizes **structured JSON logging** for better monitoring and integration with log management systems. It's also designed to avoid re-processing tasks that already have an AI-generated comment, making it safe to run repeatedly.


## Testing
**The script was generated via Gemini 2.5 pro - with minor adjustments on my end to fix functionality**

Tested on dogshit hardware(Dell R620) with no GPU acceleration.
I have everything running on RKE2 kubernetes, but am limited by ESXI licensing for the number of CPUs I can throw at it - 8.  (hopefully proxmox someday but it's my homelab and I do this all day for work too)
Typical response time from Ollama with mistral is 10-15 mins when using the dogshit hardware so I set the timeout high in the script, but I assume with some GPU acceleration and newer generation CPUs it would do much better. 

It was tested against OpenProject 12 and 13. Both with 10-15 projects and 100 or so tasks in total. 

I run it nightly as a cronjob. 

## Features

* **Multi-Project Processing:** Fetches and processes tasks from all projects accessible by the configured API token.
* **Local LLM Integration:** Utilizes a locally running Ollama instance to generate contextual information for each task.
* **Contextual Comments:** Adds the AI-generated context as a comment to the corresponding OpenProject task.
* **Avoids Duplication:** Checks for existing AI-generated comments (based on a specific marker) to prevent re-processing already enhanced tasks.
* **Structured JSON Logging:** Outputs logs in JSON format to standard output, making them easy to parse, filter, and integrate with log management systems.
* **Configurable:** Easy to configure OpenProject details, Ollama settings, and the LLM prompt via environment variables or directly in the script.

## Prerequisites

1.  **Python 3.x:** Ensure you have Python 3 installed.
2.  **Pip:** Python package installer.
3.  **OpenProject Instance:** Access to an OpenProject (tested with versions 12 and 13) instance with API access enabled.
    * You'll need an API Token from your OpenProject user profile.
    * The API token must have permissions to list projects, read work packages, and add comments/activities to them in all target projects.
4.  **Ollama Installed and Running:**
    * Ollama must be installed on your server/machine.
    * You need to have pulled a model that Ollama will serve (e.g., `ollama pull mistral`, `ollama pull llama3`).
    * Ollama should be accessible (default: `http://localhost:11434`).
5.  **Required Python Libraries:**
    * `requests`: For making HTTP API calls.
    Install with:
    ```bash
    pip install requests
    ```
    (The `logging`, `json`, `os`, `sys`, `time`, `datetime` modules are part of the Python standard library.)

## Configuration

The script can be configured in a few ways:

1.  **Environment Variables (Recommended):**
    Set the following environment variables before running the script:
    * `OPENPROJECT_URL`: Your OpenProject instance URL (e.g., `https://your-openproject.example.com`).
    * `OPENPROJECT_API_TOKEN`: Your OpenProject API token.
    * `OLLAMA_API_URL` (Optional): The URL for your Ollama API (defaults to `http://localhost:11434/api/generate`).
    * `OLLAMA_MODEL_NAME` (Optional): The name of the model Ollama should use (defaults to `mistral`).
    * `VERIFY_SSL` : A boolean value to determine if the requests module should verify SSL. 

2.  **`.env` File:**
    Create a `.env` file in the same directory as the script with the following content:
    ```env
    OPENPROJECT_URL=https://your-openproject.example.com
    OPENPROJECT_API_TOKEN=your_very_long_api_token_here
    OLLAMA_MODEL_NAME=mistral
    OLLAMA_API_URL=http://localhost:11434/api/generate
    VERIFY_SSL=True 
    ```
    The script will automatically try to load variables from this file if it exists.

## Usage

1.  Ensure all prerequisites are met and configurations are set up.
2.  Make sure your Ollama service is running and the specified model is available.
3.  Run the Python script from your terminal(or use the provided Dockerfile):
    ```bash
    python your_script_name.py
    ```
    To save the JSON logs to a file, you can redirect the output:
    ```bash
    python your_script_name.py > script_run.log
    ```
    Or append to an existing log file:
    ```bash
    python your_script_name.py >> script_run.log
    ```

The script will then:
* Connect to your OpenProject instance.
* Fetch all projects accessible by the API token.
* For each project:
    * Fetch its tasks.
    * For each task:
        * Check if an AI-generated comment already exists.
        * If not, query Ollama for additional context.
        * Add the generated context as a new comment to the task in OpenProject.
* Output logs in JSON format to standard output.
* Print a final JSON summary of its actions.

## Key Script Components

* **JSON Logging Setup:**
    * `JsonFormatter` class: Custom formatter to output log records as JSON.
    * `logger` instance: Configured application logger using the `JsonFormatter`.
* **Configuration Section:** Defines URLs, API keys, model names, and prompt templates.
* **OpenProject API Functions:**
    * `_openproject_api_request()`: Generic helper for making API requests and handling common errors.
    * `get_all_accessible_projects()`: Fetches all projects the API token can access.
    * `get_openproject_tasks_for_project()`: Fetches tasks for a specific project.
    * `get_task_activities()`: Fetches comments/activities for a task.
    * `has_ai_generated_comment()`: Checks if a task was previously processed by this script.
    * `add_comment_to_openproject_task()`: Adds the AI context as a comment to a task.
* **Ollama LLM Function:**
    * `get_context_from_ollama()`: Constructs a prompt, queries the local Ollama model, and returns the generated context.
* **Main Processing Logic (`main()`):**
    * Orchestrates the workflow: fetches all projects, then iterates through each project's tasks, checks for existing comments, calls Ollama, and updates OpenProject.

## Customization

* **`LLM_PROMPT_TEMPLATE`:** This string variable is crucial for the quality of context generated by the LLM. Modify this prompt to better suit the type of information you want the LLM to provide.
* **`AI_COMMENT_MARKER`:** This string (`🤖 AI Generated Context:\n\n`) is used to identify comments made by the script.
* **`OLLAMA_MODEL_NAME`:** Change this to use different models available in Ollama.
* **Ollama Request Options:** Within `get_context_from_ollama()`, you can adjust parameters like `temperature` and `num_predict` in the `payload["options"]` dictionary.
* **JSON Log Structure:** The `JsonFormatter` class can be modified if you need to change the structure or add/remove fields from the JSON logs.
* **Project Pagination:** The `get_all_accessible_projects()` function uses a `pageSize` of 500. If you have significantly more projects, you might need to implement full pagination logic within that function (checking `_links['next']` from the API response).
* **Task Filtering:** If you need to filter tasks *within* each project (e.g., by status or type), you can add `params` to the `_openproject_api_request` call within `get_openproject_tasks_for_project`. Refer to the OpenProject API documentation for filter syntax.

## Troubleshooting & Notes

* **Interpreting JSON Logs:** Each line of output is a self-contained JSON object. You can use tools like `jq` on the command line to pretty-print, filter, and query these logs. Example: `python your_script_name.py | jq '. | select(.level=="ERROR")'`
* **API Permissions:** Ensure the OpenProject API token has permissions to list projects, and then read/update work packages within those projects.
* **Ollama Issues:** Ensure Ollama is running, accessible, and the model is pulled.
* **Prompt Engineering:** The quality of LLM output heavily depends on the `LLM_PROMPT_TEMPLATE`.
* **Rate Limiting:** For very large instances, consider adding a small `time.sleep()` in the loops if you encounter API rate limits (though less common with self-hosted OpenProject).
* **OpenProject Version:** Tested with OpenProject 12 and general API v3 stability for version 13. Always consult your specific OpenProject version's API documentation if issues arise.

---

This script aims to provide a robust way to enhance your OpenProject tasks using local AI capabilities with clear, structured logging.

import requests
import json
import os
import time
import logging
import sys # For stdout handler
from datetime import datetime # For ISO timestamps

# --- JSON Logging Setup ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage() if isinstance(record.msg, str) else None,
            "module": record.module,
            "funcName": record.funcName,
            "lineNumber": record.lineno,
        }
        if isinstance(record.msg, dict):
            log_record.update(record.msg) # Merge dict message
        
        # Add any extra fields
        if hasattr(record, 'extra_fields') and isinstance(record.extra_fields, dict):
            log_record.update(record.extra_fields)

        # Handle exc_info for exceptions
        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)
        if record.exc_text: # For logger.exception()
             log_record['exception_text'] = record.exc_text


        return json.dumps(log_record)

# Configure logger
logger = logging.getLogger("OpenProjectOllamaSync")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.propagate = False # Prevent duplicate logs if root logger is also configured

# --- Helper function to convert string to boolean ---
def str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False # Or True, depending on desired default for None
    return value.lower() in ('true', '1', 't', 'y', 'yes')

# --- Configuration ---
OPENPROJECT_URL = os.getenv("OPENPROJECT_URL", "https://your-openproject-instance.com")
API_TOKEN = os.getenv("OPENPROJECT_API_TOKEN", "fake-api-token")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "https://ollama-url.com/api/generate")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "mistral")
# Correctly initialize VERIFY_SSL as a boolean
VERIFY_SSL = str_to_bool(os.getenv("VERIFY_SSL", "True"))
OLLAMA_REQUEST_TIMEOUT = 1800 # 30 mins

AI_COMMENT_MARKER = "🤖 AI Generated Context:\n\n"
LLM_PROMPT_TEMPLATE = """
Task Subject: {subject}
Task Description:
{description}

Based *only* on the task subject and description above, provide additional context that would be helpful for understanding or starting this task.
Consider potential ambiguities, key questions to ask, or immediate next steps.
Keep the output concise, focused, and directly related to the provided information. Do not add any preamble like "Additional Context:".
Provide only the helpful context itself.
"""

# --- OpenProject API Functions ---
def _openproject_api_request(method, endpoint_suffix, params=None, payload=None):
    if not OPENPROJECT_URL or not API_TOKEN:
        logger.error({"event": "config_error", "message": "OpenProject URL or API Token is not configured."})
        return None

    auth = ('apikey', API_TOKEN)
    full_url = f"{OPENPROJECT_URL}{endpoint_suffix}"
    headers = {'Content-Type': 'application/json'}
    
    log_data = {
        "event": "openproject_api_request",
        "method": method.upper(),
        "url": full_url,
        "params": params if params else {}
    }
    # logger.debug(log_data) # Use debug for potentially verbose data

    try:
        if method.lower() == 'get':
            response = requests.get(full_url, auth=auth, params=params, headers=headers, timeout=30, verify=VERIFY_SSL)
        elif method.lower() == 'patch':
            response = requests.patch(full_url, auth=auth, json=payload, headers=headers, timeout=30, verify=VERIFY_SSL)
        elif method.lower() == 'post':
            response = requests.post(full_url, auth=auth, json=payload, headers=headers, timeout=30, verify=VERIFY_SSL)
        else:
            logger.error({"event": "unsupported_http_method", "method": method, "url": full_url})
            return None
            
        response.raise_for_status() # Will raise an HTTPError for bad responses (4xx or 5xx)
        
        # For POST requests, a 201 (Created) is common. 204 (No Content) can also occur.
        # If the request was successful and there's content, return it. Otherwise, return True for success.
        if response.status_code == 204: # No Content
            return True 
        if response.content: # Check if there is content to decode
            return response.json()
        return True # Success, but no content or not JSON (e.g. 200 OK with no body)

    except requests.exceptions.Timeout:
        logger.error({"event": "openproject_api_timeout", "method": method.upper(), "url": full_url})
    except requests.exceptions.RequestException as e:
        error_details = {"error_message": str(e)}
        if hasattr(e, 'response') and e.response is not None:
            error_details["status_code"] = e.response.status_code
            try:
                error_details["response_body"] = e.response.json()
            except json.JSONDecodeError:
                error_details["response_body"] = e.response.text
        logger.error({"event": "openproject_api_request_error", "method": method.upper(), "url": full_url, "details": error_details}, exc_info=False) # Set exc_info=True for full traceback if needed
    return None

def get_all_accessible_projects():
    logger.info({"event": "fetching_all_projects_started"})
    params = {'pageSize': 500} 
    data = _openproject_api_request('get', "/api/v3/projects", params=params)
    if data and '_embedded' in data and 'elements' in data['_embedded']:
        projects = data['_embedded']['elements']
        logger.info({"event": "fetching_all_projects_success", "project_count": len(projects)})
        return projects
    else:
        logger.warning({"event": "fetching_all_projects_failed", "message": "No projects found or error occurred."})
        return []

def get_openproject_tasks_for_project(project_identifier_or_id, project_name):
    log_context = {"project_identifier": project_identifier_or_id, "project_name": project_name}
    logger.info({"event": "fetching_project_tasks_started", **log_context})
    api_suffix = f"/api/v3/projects/{project_identifier_or_id}/work_packages"
    # Add filter to get only open tasks, adjust as needed for your definition of "open"
    # Example: [{"status_id":{"operator":"o"}}]  # 'o' typically means open statuses
    # You might need to find the correct status IDs for "open" in your OpenProject instance.
    # For simplicity, this example fetches all tasks. You can add filters here:
    params = {
        # "filters": json.dumps([
        #     {"status": {"operator": "o"}}, # This is a common way to filter by open statuses
        #     # {"assigneeOrGroup": {"operator": "=", "values": ["me"]}} # Example: assigned to me
        # ])
    }
    data = _openproject_api_request('get', api_suffix, params=params if params.get("filters") else None)

    if data and '_embedded' in data and 'elements' in data['_embedded']:
        tasks = data['_embedded']['elements']
        logger.info({"event": "fetching_project_tasks_success", "task_count": len(tasks), **log_context})
        return tasks
    logger.warning({"event": "fetching_project_tasks_failed", "message": "No tasks found or error.", **log_context})
    return []

def get_task_activities(task_id):
    # logger.debug({"event": "fetching_task_activities_started", "task_id": task_id}) # Can be noisy
    api_suffix = f"/api/v3/work_packages/{task_id}/activities"
    data = _openproject_api_request('get', api_suffix)
    if data and '_embedded' in data and 'elements' in data['_embedded']:
        return data['_embedded']['elements']
    return []

def has_ai_generated_comment(task_id):
    activities = get_task_activities(task_id)
    if not activities:
        return False
    for activity in activities:
        # Check if the activity itself is a comment and has the marker
        # The structure for comments via activities might differ slightly.
        # We need to look for details._type == "Comment" or similar if activities endpoint includes non-comment events.
        # Assuming 'comment' field exists directly in the activity for comments.
        comment_data = activity.get('comment', {}) # If comment is nested
        if not isinstance(comment_data, dict) and activity.get("_type") == "WorkPackageComment": # Simpler structure for some activity types
             comment_data = activity.get("comment", {})


        # If the activity itself represents the comment text directly (less common)
        # or if it's nested under a 'details' attribute for comments
        details_comment_raw = None
        if activity.get("_type") == "Comment" and 'comment' in activity: # Check common OpenProject activity structure
            comment_data = activity['comment']


        if isinstance(comment_data, dict):
            comment_raw = comment_data.get('raw', '')
            if comment_raw and comment_raw.startswith(AI_COMMENT_MARKER):
                logger.info({"event": "existing_ai_comment_found", "task_id": task_id, "source": "comment_field"})
                return True
        
        # Also check if the activity is a direct comment, not just an update with a comment field
        # This part might need adjustment based on the exact structure of your activity entries.
        # Often, activities are generic and the "comment" is a specific detail of an update.
        # However, if posting to /activities creates a specific "comment" activity type:
        if 'details' in activity and isinstance(activity['details'], list):
            for detail in activity['details']:
                if detail.get('type') == 'Comment' and isinstance(detail.get('raw'), str):
                    if detail['raw'].startswith(AI_COMMENT_MARKER):
                        logger.info({"event": "existing_ai_comment_found_in_activity_details", "task_id": task_id})
                        return True


    return False

def add_comment_to_openproject_task(task_id, comment_text):
    log_context = {"task_id": task_id}
    logger.info({"event": "adding_comment_via_activities_started", **log_context})
    # Endpoint for posting comments as activities
    api_suffix = f"/api/v3/work_packages/{task_id}/activities"
    payload = {
        # "_type": "Comment", # Some APIs might require specifying the type of activity
        "comment": {"raw": comment_text}
    }
    # Using 'post' to create a new activity (comment)
    success = _openproject_api_request('post', api_suffix, payload=payload)
    
    if success: # This will be True if the request returned 200/201/204 or a JSON body
        logger.info({"event": "adding_comment_via_activities_success", **log_context})
        return True
    else: # This will be True if _openproject_api_request returned None (an error occurred)
        logger.error({"event": "adding_comment_via_activities_failed", **log_context})
        return False

# --- Ollama LLM Function ---
def get_context_from_ollama(task_id, subject, description):
    log_context = {"task_id": task_id, "subject": subject[:50]+"..."} # Truncate subject for brevity
    if not subject and not description:
        logger.warning({"event": "ollama_skip_empty_input", **log_context})
        return None

    prompt = LLM_PROMPT_TEMPLATE.format(subject=subject, description=description if description else "Not provided.")
    payload = {
        "model": OLLAMA_MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 200}
    }
    
    logger.info({"event": "ollama_query_started", "ollama_model": OLLAMA_MODEL_NAME, **log_context})
    
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=OLLAMA_REQUEST_TIMEOUT, verify=VERIFY_SSL)
        response.raise_for_status()
        response_data = response.json()
        generated_context = response_data.get("response", "").strip()
        
        if generated_context:
            logger.info({"event": "ollama_query_success", "ollama_model": OLLAMA_MODEL_NAME, **log_context})
            return generated_context
        else:
            logger.warning({"event": "ollama_empty_response", "ollama_model": OLLAMA_MODEL_NAME, **log_context})
            return None
    except requests.exceptions.Timeout:
        logger.error({"event": "ollama_query_timeout", "ollama_model": OLLAMA_MODEL_NAME, **log_context})
    except requests.exceptions.RequestException as e:
        error_details = {"error_message": str(e)}
        if hasattr(e, 'response') and e.response is not None:
            error_details["status_code"] = e.response.status_code
            try:
                error_details["response_body"] = e.response.json()
            except json.JSONDecodeError:
                error_details["response_body"] = e.response.text
        logger.error({"event": "ollama_query_request_error", "ollama_model": OLLAMA_MODEL_NAME, "details": error_details, **log_context}, exc_info=False)
    except json.JSONDecodeError as e:
        error_details = {"error_message": str(e), "response_text": response.text if 'response' in locals() else "N/A"}
        logger.error({"event": "ollama_query_json_decode_error", "ollama_model": OLLAMA_MODEL_NAME, "details": error_details, **log_context}, exc_info=False)
    return None

# --- Main Processing Logic ---
def main():
    logger.info({"event": "script_started", "script_version": "v4-json-logging-activities-comment", "verify_ssl_status": VERIFY_SSL})

    config_ok = True
    if not OPENPROJECT_URL or OPENPROJECT_URL == "https://your-openproject-instance.com": # Basic check
        logger.critical({"event": "config_missing", "parameter": "OPENPROJECT_URL"})
        config_ok = False
    if not API_TOKEN or API_TOKEN == "YOUR_OPENPROJECT_API_TOKEN": # Basic check
        logger.critical({"event": "config_missing", "parameter": "OPENPROJECT_API_TOKEN"})
        config_ok = False
    if not config_ok:
        logger.info({"event": "script_aborted_due_to_config"})
        return

    all_projects = get_all_accessible_projects()
    if not all_projects:
        logger.info({"event": "script_exiting_no_projects"})
        return

    total_tasks_fetched_overall = 0
    total_tasks_processed_for_ai_overall = 0
    total_comments_added_overall = 0
    total_tasks_skipped_overall = 0
    
    logger.info({"event": "multi_project_processing_started", "total_projects_to_process": len(all_projects)})

    for project_index, project in enumerate(all_projects):
        project_id = project.get('id')
        project_identifier = project.get('identifier') # Use identifier for fetching tasks
        project_name = project.get('name', f"Unnamed Project (ID: {project_id})")
        project_log_context = {"project_id_op": project_id, "project_identifier": project_identifier, "project_name": project_name, "project_index": project_index + 1, "total_projects": len(all_projects)}

        logger.info({"event": "project_processing_started", **project_log_context})

        # Pass project_identifier (which could be ID or string identifier)
        tasks = get_openproject_tasks_for_project(project_identifier, project_name) 
        
        if not tasks:
            logger.info({"event": "project_processing_skipped_no_tasks", **project_log_context})
            continue
        
        total_tasks_fetched_overall += len(tasks)
        project_tasks_processed_for_ai = 0
        project_comments_added = 0
        project_tasks_skipped = 0


        for task_index, task in enumerate(tasks):
            task_id = task.get('id')
            subject = task.get('subject', 'No Subject')
            description_data = task.get('description', {})
            description_raw = description_data.get('raw', '') if isinstance(description_data, dict) else ''
            # lock_version = task.get('lockVersion') # No longer needed for adding comments via activities

            task_log_context = {**project_log_context, "task_id": task_id, "task_subject": subject, "task_index": task_index + 1, "total_tasks_in_project": len(tasks)}
            logger.info({"event": "task_processing_started", **task_log_context})

            if task_id is None: # Removed lock_version check as it's not used for new comment method
                logger.warning({"event": "task_skipped_missing_data", "reason": "Missing Task ID", **task_log_context})
                total_tasks_skipped_overall += 1 # Count this as skipped
                project_tasks_skipped +=1
                continue
            
            if has_ai_generated_comment(task_id):
                total_tasks_skipped_overall += 1
                project_tasks_skipped +=1
                logger.info({"event": "task_skipped_existing_ai_comment", **task_log_context})
                continue

            context = get_context_from_ollama(task_id, subject, description_raw) 
            total_tasks_processed_for_ai_overall += 1
            project_tasks_processed_for_ai +=1
            
            if context:
                full_comment_text = f"{AI_COMMENT_MARKER}{context}"
                # Call updated function without lock_version
                if add_comment_to_openproject_task(task_id, full_comment_text):
                    total_comments_added_overall += 1
                    project_comments_added +=1
            else:
                logger.info({"event": "task_no_context_generated", **task_log_context})
            
        logger.info({
            "event": "project_processing_finished", 
            "tasks_in_project": len(tasks),
            "tasks_processed_for_ai_in_project": project_tasks_processed_for_ai,
            "comments_added_in_project": project_comments_added,
            "tasks_skipped_in_project": project_tasks_skipped,
            **project_log_context
        })

    summary_stats = {
        "total_projects_processed": len(all_projects),
        "total_tasks_fetched_overall": total_tasks_fetched_overall,
        "total_tasks_skipped_overall_existing_comment_or_missing_data": total_tasks_skipped_overall,
        "total_tasks_processed_for_ai_overall": total_tasks_processed_for_ai_overall,
        "total_new_ai_comments_added_overall": total_comments_added_overall
    }
    logger.info({"event": "script_finished", "summary": summary_stats})

if __name__ == "__main__":
    # The 'global VERIFY_SSL' declaration was removed from here as it's not needed
    # for assignments to module-level globals within this top-level execution block.
    
    # Load .env file if present
    if os.path.exists(".env"):
        logger.info({"event": "loading_env_file", "path": ".env"})
        try:
            with open(".env") as f:
                for line_number, line in enumerate(f, 1):
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip() # Remove potential whitespace around key
                        value = value.strip() # Remove potential whitespace around value
                        os.environ[key] = value # Set environment variable
                        # Update globals if they were initialized before .env was loaded
                        if key == "OPENPROJECT_URL": OPENPROJECT_URL = value
                        if key == "OPENPROJECT_API_TOKEN": API_TOKEN = value
                        if key == "OLLAMA_API_URL": OLLAMA_API_URL = value
                        if key == "OLLAMA_MODEL_NAME": OLLAMA_MODEL_NAME = value
                        if key == "VERIFY_SSL": 
                            VERIFY_SSL = str_to_bool(value) # Convert to bool when loading from .env
        except Exception as e:
            logger.error({"event": "env_file_load_error", "error": str(e)}, exc_info=True)
    else: 
        pass # VERIFY_SSL retains its value from initial os.getenv or is already correctly boolean

    main()
import os
import time
import uuid
from pathlib import Path
import requests
import json

# control VERBOSE mode
VERBOSE = True
# VERBOSE = False

## ----- Configure Models ---------

from dotenv import load_dotenv

# Load a project-level .env file if one exists. By default, load_dotenv does not
# replace a value already supplied by the user's environment.
load_dotenv(Path(__file__).with_name(".env"))

API_KEY = os.getenv("OPENCODE_API_KEY")

if API_KEY:
    # OpenCode Go subscription
    MODEL = "mimo-v2.5"
    ZEN_CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
else:
    # Keyless free fallback
    MODEL = "mimo-v2.5-free"
    ZEN_CHAT_URL = "https://opencode.ai/zen/v1/chat/completions"

# OpenCode requires clients to identify themselves with a real User-Agent
# and to send a stable per-conversation session id (used for routing and
# prompt caching) -- see https://opencode.ai/docs/go .  Requests without
# the session id are rejected with a 400 error on both endpoints.
HEADERS = {"Content-Type": "application/json",
           "User-Agent": "toy-agent/1.0",
           "x-opencode-session": str(uuid.uuid4())}

if API_KEY:
    HEADERS["Authorization"] = f"Bearer {API_KEY}"


## --------- System Prompt ----------

SYSTEM = """
You are a programming agent which works efficiently with absolutely no nonsense.

Follow these rules while working.
- Always read a file before you write or edit it.
- Confine all filesystem accesses of any kind safely to the sandbox (the
  `sandbox` directory in the same folder as your source).
- Keep calling tools until the requested task is successfully accomplished (but
  always make sure each new tool call is different in some detail from previous
  tool calls).
- When you have completed a task, concisely and precisely summarize exactly how
  you accomplished it.
"""

# ------ Sandboxing --------

# Create a `sandbox` sub-directory (if it does not already exist) 
# in the directory from which the agent code was launched

SANDBOX_DIR = (Path(__file__).resolve().parent / "sandbox").resolve()
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

# Helper function to make sure that paths to be used in tool calls
# lie within the sandbox.

def resolve_in_sandbox(file_name: str) -> Path:
    resolved = (SANDBOX_DIR / file_name).resolve()
    if not resolved.is_relative_to(SANDBOX_DIR):
        raise ValueError(f"path escapes the sandbox: {file_name}")
    return resolved

# ------ Tools --------

def read_file(file_name: str) -> str:
    path = resolve_in_sandbox(file_name)
    if not path.is_file():
        return (f"ERROR: file not found: {file_name} – "
                f"directory contains: {list_files()}")
    return path.read_text()

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Gets the full contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string",
                              "description": "The path of the file to read"},
            },
            "required": ["file_name"],
        },
    },
}

def list_files() -> list[str]:
    return sorted(p.name for p in SANDBOX_DIR.iterdir() if p.is_file())

LIST_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description":
        ("Lists all files in the sandbox directory; "
         "returns only files, not directories."),
        "parameters": {"type": "object", "properties": {}},
    },
}

def write_file(file_name: str, contents: str, mode: str = "append") -> str:
    path = resolve_in_sandbox(file_name)
    if path.is_dir():
        return f"ERROR: {file_name} is a directory"
    py_mode = "a" if mode == "append" else "w"
    verb = "appended" if mode == "append" else "wrote"
    with path.open(mode=py_mode, encoding="utf-8") as f:
        n = f.write(contents)
    return f"{verb} {n} characters to {file_name}"

WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Writes to a file. `mode='append'` (default) adds `contents` to the"
            " end of the file, creating it if needed – `contents` must be ONLY "
            "the new text to add, never a repeat of content already in the "
            "file. `mode='overwrite'` replaces the entire file with `contents`."
            " Always `read_file` first if you need to know the current contents"
            " before deciding what to send."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "The path of the file to which to write"},
                "contents": {
                    "type": "string",
                    "description": (
                        "For append: only the new text to add. "
                        "For overwrite: the full desired file contents.")},
                "mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "description": "Whether to append to or overwrite the file."
                    " Defaults to append."},
            },
            "required": ["file_name", "contents"],
        },
    },
}

# name -> function, for the loop to dispatch
TOOLS = {"read_file": read_file, "list_files": list_files,
         "write_file": write_file}
# what actually gets sent to the model
TOOLS_SCHEMATA = [READ_FILE_SCHEMA, LIST_FILES_SCHEMA, WRITE_FILE_SCHEMA]

## ------ model call -------

def call_zen(messages: list, tools: list) -> dict:
    resp = requests.post(
        ZEN_CHAT_URL,
        headers=HEADERS,
        json={"model": MODEL, "messages": messages, "tools": tools},
        timeout=60,
    )
    resp.raise_for_status()

    payload = resp.json()
    if not payload.get("choices"):
        raise RuntimeError(f"Zen returned no choices: {payload}")
    return payload["choices"][0]["message"]

# -----  Agentic loop -----

# Cap on the number of model calls made for a single user request.
MAX_TURNS = 25

def agentic_loop(messages: list) -> None:
    turns = 0
    while turns < MAX_TURNS:
        turns += 1
        # give the current message history and tool list to the model
        message = call_zen(messages, TOOLS_SCHEMATA)
        # add the message returned from the model to the message history
        messages.append(message)
        # if the returned message contains a user message, then print it
        if message.get("content"):
            print(message["content"])

        # get the tool calls proposed by the model
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return  # the model decided it is finished – the normal exit

        # for each tool call
        for tc in tool_calls:
            # look up the name of the function representing the tool call
            name = tc["function"]["name"]
            # get the argument the model has proposed for the tool call
            raw_arguments = tc["function"].get("arguments") or "{}"

            if VERBOSE:
                print(f"---\nCalling {name} with arguments {raw_arguments}")

            # if the model has proposed a tool that is not in our available
            # tools, then prepare an informative error message indicating what
            # tools are available
            if name not in TOOLS:
                result = f"ERROR: unknown tool: {name} – available: {list(TOOLS)}"
            else:
                try:
                    # make the tool call
                    result = TOOLS[name](**json.loads(raw_arguments))
                except Exception as e:
                    result = f"ERROR: {name} failed: {type(e).__name__}: {e}"
            # add the result of the tool call (or the constructed error message)
            # to the message history to become part of the context for future
            # calls.
            if VERBOSE:
                print(f"Result: {result}\n---\n")
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})

    print(f"\n[toy-agent] Stopped: hit the MAX_TURNS = {MAX_TURNS} cap for this request. "
          "The task may be unfinished.")

#------- Harness Opening Message -----------

def print_intro():
    print("Welcome to a toy programming agent!")
    print("You will be prompted for input via the :")
    print("\nThe current model is " + MODEL)
    print("\n Type 'EXIT' to exit the program\n\n")

#------ Harness entry point -------

if __name__ == "__main__":
    # Include the system prompt as the first item in the messages list data structure
    messages = [{"role": "system", "content": SYSTEM}]
    print_intro()

    user = input(": ")
    # REPL
    while user != "EXIT":
        messages.append({"role": "user", "content": user})

        # model interaction
        agentic_loop(messages)

        # new user input 
        time.sleep(1.0)
        user = input("\n: ")

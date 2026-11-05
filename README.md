# AI Interview Assistant & Interview Copilot

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](http://www.apache.org/licenses/LICENSE-2.0)

AI-Assistant is an open-source, real-time AI interview assistant for technical and behavioral interview preparation.

It provides a floating desktop interface that can accept questions through text, voice, meeting audio, or screen analysis and generate AI-powered answers using your selected AI provider.

---

## Features

* 🤖 **Multiple AI Providers**

  * Groq
  * OpenAI
  * Mistral AI
  * Ollama

* 🎤 **Voice Input**

  * Ask questions using your microphone.

* 🎧 **Meeting Audio Transcription**

  * Capture system/loopback audio from applications such as:

    * Zoom
    * Google Meet
    * Microsoft Teams
  * Transcribe locally with faster-whisper; the model is downloaded on first use.

* 🖥️ **Screen Analysis**

  * Capture the current screen.
  * Describe visible content and read text, including questions, code, and error messages,
    with the configured provider's vision model.
  * Fall back to built-in Windows OCR for readable text when no provider API key is configured.

* 📄 **Resume-Aware Answers**

  * Upload your PDF, DOCX, or TXT resume.
  * Use your resume information while generating answers.

* 🌐 **Live Web Search**

  * Uses DuckDuckGo search results to provide additional context.

* 🪟 **Floating Desktop Overlay**

  * Always-on-top interface.
  * Toggle the overlay using:

```text
Ctrl + Shift + Space
```

---

# How It Works

```text
Interview Question
        |
        v
+-------------------------+
| Question Input          |
|                         |
| • Type                  |
| • Voice                 |
| • Meeting Audio         |
| • Screen Analysis       |
+------------+------------+
             |
             v
+-------------------------+
| Context                 |
|                         |
| • Resume                |
| • Web Search            |
+------------+------------+
             |
             v
+-------------------------+
| AI Provider             |
|                         |
| • Groq                  |
| • OpenAI                |
| • Mistral               |
| • Ollama                |
+------------+------------+
             |
             v
      Generated Answer
             |
             v
       AI Assistant UI
```

---

# Requirements

Before installing the application, make sure you have:

### Operating System

* Windows 10 Build 2004 or later
* Windows 11

> Meeting-audio loopback and Windows overlay functionality currently depend on Windows-specific APIs.

### Python

* Python 3.10 or later

Check your Python version:

```cmd
python --version
```

### AI Provider

An AI provider is needed for AI-generated answers and cloud-based screen analysis.
Screen text can still be extracted offline with Windows OCR when no API key is set.
For AI features, configure at least one of:

* Groq API key
* OpenAI API key
* Mistral AI API key
* Local Ollama installation

### Hardware

For voice and meeting features:

* Working microphone
* Working audio-output/loopback device

---

# Installation

## Step 1: Clone the Repository

Open **Command Prompt** or **PowerShell** and run:

```cmd
git clone https://github.com/Yashwanthgowda1/AI-Assistant.git
```

Move into the project directory:

```cmd
cd AI-Assistant
```

---

## Step 2: Create a Virtual Environment

Create a Python virtual environment:

```cmd
python -m venv venv
```

Activate the virtual environment:

### Command Prompt

```cmd
venv\Scripts\activate
```

### PowerShell

```powershell
venv\Scripts\Activate.ps1
```

After activation, you should see something similar to:

```text
(venv) C:\...\AI-Assistant>
```

---

## Step 3: Install Dependencies

Install the required Python packages:

```cmd
pip install -r requirements.txt
```

---

## Step 4: Create the `.env` File

Copy the example environment file:

### Command Prompt

```cmd
copy .env.example .env
```

### PowerShell

```powershell
Copy-Item .env.example .env
```

---

# Configuration

Open the `.env` file and configure your preferred AI provider.

## Option 1: Groq

```env
AI_PROVIDER=groq
AI_MODEL=llama-3.3-70b-versatile
GROQ_API_KEY=your_groq_api_key
```

## Option 2: OpenAI

```env
AI_PROVIDER=openai
AI_MODEL=your_openai_model
OPENAI_API_KEY=your_openai_api_key
```

## Option 3: Mistral AI

```env
AI_PROVIDER=mistral
AI_MODEL=your_mistral_model
MISTRAL_API_KEY=your_mistral_api_key
```

## Option 4: Ollama

Install and run Ollama locally, then configure:

```env
AI_PROVIDER=ollama
AI_MODEL=your_local_model
```

---

# Environment Variables

| Variable          | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `AI_PROVIDER`     | AI provider: `groq`, `openai`, `mistral`, or `ollama` |
| `AI_MODEL`        | Model used by the selected provider                   |
| `GROQ_API_KEY`    | Groq API key                                          |
| `OPENAI_API_KEY`  | OpenAI API key                                        |
| `MISTRAL_API_KEY` | Mistral AI API key                                    |

> Never commit your `.env` file or API keys to GitHub.

---

# Run the Application

There are two ways to start the application.

## Method 1: Using `run.bat`

From the project directory:

```cmd
run.bat
```

The script will set up the environment, install dependencies, and launch the application.

---

## Method 2: Run Using Python

If the environment is already configured:

```cmd
python main.py
```

---

# Quick Start

After starting the application:

### Step 1: Enter a Question

Type an interview question into the input box.

Example:

```text
Explain the difference between Selenium and Playwright.
```

Click the button to generate an answer.

---

### Step 2: Use Voice Input

Click the **Microphone** button.

Speak your question.

The application converts your voice input into text and sends it to the configured AI provider.

---

### Step 3: Analyse the Screen

Click:

```text
Analyse Screen
```

With a configured provider API key, the application uses that provider's vision model
to extract the question and generate an answer. Without an API key, Windows OCR extracts
visible text locally and places it in the question field; review it and press **Send**
to get an AI answer after configuring a provider.

This is useful for questions displayed in:

* Browser pages
* Coding platforms
* Documents
* Interview applications

---

### Step 4: Upload Your Resume

Click:

```text
Upload Resume
```

Select your resume:

```text
PDF
DOCX
TXT
```

The application extracts the resume content and uses it as context when generating answers.

---

### Step 5: Enable Meeting Audio

Enable:

```text
Meeting
```

The application captures supported system/loopback audio and transcribes it locally with
faster-whisper. The base model is downloaded the first time meeting transcription starts;
subsequent transcription runs locally without sending audio to a speech-recognition service.

Supported meeting applications can include:

* Zoom
* Google Meet
* Microsoft Teams

---

### Step 6: Select AI Provider

Open the **Settings** panel.

Select your preferred provider:

```text
Groq
OpenAI
Mistral
Ollama
```

You can also configure the model and API settings from the application where supported.

---

### Step 7: Toggle the Overlay

Use the global keyboard shortcut:

```text
Ctrl + Shift + Space
```

to show or hide the floating assistant window.

---

# Example Workflow

A typical workflow looks like this:

```text
1. Clone repository
        ↓
2. Install dependencies
        ↓
3. Configure .env
        ↓
4. Select AI provider
        ↓
5. Start application
        ↓
6. Upload resume
        ↓
7. Enter / speak / capture question
        ↓
8. AI processes the question
        ↓
9. Answer is displayed
```

---

# Project Structure

```text
AI-Assistant/
│
├── main.py
├── __main__.py
├── ai_client.py
├── meeting_listener.py
├── voice_client.py
├── image_client.py
├── resume_client.py
├── search_client.py
├── stealth.py
├── run.bat
├── requirements.txt
├── .env.example
└── README.md
```

| File                  | Purpose                                 |
| --------------------- | --------------------------------------- |
| `main.py`             | Application entry point and PyQt5 GUI   |
| `__main__.py`         | Application module entry point          |
| `ai_client.py`        | AI provider integration                 |
| `meeting_listener.py` | Meeting audio capture and transcription |
| `voice_client.py`     | Microphone and voice input              |
| `image_client.py`     | Screenshot capture and screen analysis  |
| `resume_client.py`    | Resume parsing                          |
| `search_client.py`    | DuckDuckGo web search                   |
| `stealth.py`          | Windows screen-capture exclusion        |
| `run.bat`             | Application setup and launcher          |
| `.env.example`        | Environment configuration template      |

---

# Use Cases

* Technical interview preparation
* Behavioral interview preparation
* Coding interview practice
* Resume-based interview questions
* Voice-based interview practice
* Screen-based question analysis
* Meeting audio transcription
* AI-powered answer generation
* Interview learning and practice

---

# Screen Overlay

The application provides an always-on-top floating window.

On supported Windows versions, the application can use the Windows `SetWindowDisplayAffinity` API for screen-capture exclusion.

Use:

```text
Ctrl + Shift + Space
```

to toggle the overlay.

> Screen-capture and screen-sharing behavior depends on the Windows version and the application being used.

---

# Responsible Use

This project can be used for interview preparation, practice, and learning.

Before using AI assistance during an actual interview, check the rules of the employer, interviewer, assessment platform, or interview process. Some interview processes may restrict or prohibit undisclosed AI assistance.

Use the software according to the applicable rules and requirements.

---

# Troubleshooting

## Python Command Not Found

Check that Python is installed:

```cmd
python --version
```

If the command is not recognized, install Python and ensure it is added to your system PATH.

---

## Dependencies Not Installed

Activate the virtual environment and run:

```cmd
pip install -r requirements.txt
```

---

## Application Does Not Start

Try running:

```cmd
python main.py
```

Check the terminal output for the error message.

---

## AI Provider Error

Check your `.env` file and verify:

* `AI_PROVIDER` is correct.
* `AI_MODEL` is valid.
* The required API key is configured.
* The API key is valid.

---

## Meeting Audio Is Not Detected

Check that:

* Your Windows audio output device is working.
* A loopback-compatible audio device is available.
* The required permissions are enabled.
* The meeting application is producing audio.

---

# Contributing

Contributions are welcome.

You can contribute by:

* Reporting bugs
* Improving documentation
* Adding AI providers
* Adding transcription providers
* Improving the user interface
* Adding macOS/Linux support
* Fixing bugs
* Improving performance

For larger changes, open an issue before submitting a pull request.

---

# License

This project is licensed under the **Apache License 2.0**.

[Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0)

---

# Repository

[AI-Assistant](https://github.com/Yashwanthgowda1/AI-Assistant)

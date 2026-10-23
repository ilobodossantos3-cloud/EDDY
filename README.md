# EDDY — Personal AI Assistant for Desktop

**A Python-based personal AI assistant with LLM integration, desktop automation, reminders, and optional voice interaction.**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange.svg)]()

EDDY is a personal AI assistant designed to go beyond a traditional chatbot. It combines a language-model-powered agent with desktop tools, reminders, scheduled routines, a local knowledge vault, and a browser-based heads-up display (HUD).

The project explores how LLMs can be integrated into a practical desktop environment, with configurable providers, modular capabilities, and safety controls for computer actions.

## Features

- **LLM integration:** configurable API-based models, including Inception, NVIDIA and OpenRouter, with support for local inference options.
- **Desktop HUD:** a locally served browser interface with an optional desktop window.
- **Voice capabilities:** optional speech recognition with Faster-Whisper and text-to-speech integrations, depending on configuration and installed components.
- **Desktop automation:** supported actions for launching approved applications, opening URLs, controlling media and volume, and accessing permitted files.
- **Reminders and routines:** scheduled reminders and configurable multi-step routines.
- **Modular skills:** extensible task modules for daily planning, metrics, trends and knowledge-vault queries.
- **Personal knowledge vault:** Markdown-based notes and local information storage.
- **Safety controls:** action policies, risk levels, confirmation prompts, safe mode, dry-run mode and audit logs.

## Architecture

```text
User input (text or optional microphone)
                  |
                  v
       Intent matching / LLM agent
                  |
                  v
     Action policy and validation
                  |
                  v
  Approved tools, reminders and skills
                  |
                  v
        HUD feedback / speech

Supporting components:
- Configurable cloud or local LLM providers
- Local Markdown knowledge vault
- Scheduled jobs and routines
- Security policies, confirmations and audit logs
```

The architecture separates the agent's reasoning from the tools it is permitted to execute. Actual capabilities depend on the selected provider, configuration, operating system and installed optional dependencies.

## Technology Stack

- **Language:** Python
- **AI integration:** LLM APIs and configurable provider backends
- **Backend and interfaces:** local server, REST/WebSocket components and browser-based HUD
- **Speech:** Faster-Whisper and configurable text-to-speech providers
- **Configuration and data:** YAML and Markdown
- **Testing:** pytest
- **Development environment:** Windows, with local model options where supported

## Getting Started

### Requirements

- Windows 10 or 11
- Python 3.12 recommended
- An API key for a supported LLM provider, or a configured local model
- Optional microphone, speakers and voice dependencies

### Installation

Clone the repository and enter the project directory:

```bash
git clone https://github.com/ilobodossantos3-cloud/EDDY.git
cd EDDY
```

Run the setup script in PowerShell:

```powershell
.\setup.ps1
```

Alternatively, create the environment and install the base dependencies manually:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
```

Install optional voice dependencies if needed:

```powershell
.\.venv\Scripts\pip install -r requirements-voice.txt
```

### Configuration

1. Create a local `.env` file from `.env.example` if the setup script has not already created it.
2. Add the credentials for the provider you intend to use.
3. Configure the active LLM provider, voice options and HUD settings in `config.yaml`.
4. Review `config/apps.yaml` and `config/routines.yaml` before enabling desktop actions or scheduled routines.

**Never commit `.env`, API keys, access tokens or other credentials to the repository.**

### Run EDDY

```powershell
.\start.bat
```

For a more cautious first run, use safe mode or dry-run mode:

```powershell
.\.venv\Scripts\python -m eddy --safe
```

```powershell
.\.venv\Scripts\python -m eddy --dry-run
```

## Example Use Cases

Depending on the active provider and enabled permissions, EDDY can be used to:

- Create reminders for everyday tasks.
- Open approved applications and websites.
- Perform basic web research.
- Execute supported desktop actions.
- Provide spoken responses when a compatible speech engine is configured.
- Run scheduled routines and access personal Markdown notes.

## Security and Privacy

EDDY includes safeguards intended to reduce the risk of unintended desktop actions:

- Explicit policies and validation for supported actions.
- Confirmation prompts for sensitive operations.
- Safe and dry-run modes.
- Restricted file access and application allowlisting.
- Local HUD binding and access-token protection.
- Audit logging for supported actions.

Some configurations use external LLM or speech services. Data sent to those services is subject to their respective privacy policies. Local speech recognition does not necessarily mean that the entire system operates offline.

Review the configuration and test actions in safe or dry-run mode before relying on them.

## Project Structure

```text
eddy/
├── actions/       # Desktop tools and action execution
├── engine/        # Agent logic and intent processing
├── hud_web/       # Browser-based user interface
├── llm/           # LLM provider integrations
├── security/      # Policies, validation and audit controls
├── server/        # Local server components
├── skills/        # Skill loading and integration
├── vault/         # Markdown knowledge-vault support
└── voice/         # Audio, speech recognition and synthesis

config/            # Application and routine configuration
plugins/           # Optional user plugins
scripts/           # Utility scripts
skills/            # Modular skill definitions
tests/             # Automated tests
```

## Testing

Install pytest if it is not already available:

```powershell
.\.venv\Scripts\pip install pytest
```

Run the test suite:

```powershell
.\.venv\Scripts\python -m pytest
```

Tests cover selected areas of action execution, security validation, agent integration, voice functionality and the local server. Results may depend on optional dependencies and the local environment.

## Current Status and Roadmap

EDDY is a personal project in active development. Its core structure includes text interaction, LLM integration, reminders, desktop tools and a HUD. Voice and provider integrations may require additional configuration and testing.

Planned areas of improvement include:

- Improving speech-input reliability and responsiveness.
- Expanding automated tests and integration coverage.
- Improving setup and provider configuration.
- Extending the skill system and desktop capabilities.

## Contributing

Suggestions, bug reports and contributions are welcome. Please remove credentials, personal information and private logs before opening an issue or pull request.

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

# Selenium Automated Downloader

A Python-based Selenium automation tool designed for controlled and reliable downloading scenarios. The script handles navigation, user interaction, request pacing, and download validation, ensuring stable operation over long sessions.

## Features

* **Automated Browser Control**: Uses Selenium WebDriver to handle dynamic web interfaces.
* **Configurable Timing & Pacing**: Built-in randomized waiting patterns for safe and human-like interaction.
* **Download Management**: Ensures downloaded content is handled, stored, and logged properly.
* **Error Handling & Recovery**: Automatically retries on failures and handles unexpected behavior.
* **Logging & Tracking**: Provides timestamped logs for monitoring progress and diagnosing issues.
* **Dedupe Safe Mode**: Optionally avoids re-downloading files that already exist locally.

## Project Structure

```
project-folder/
│   downloader_selenium.py      # Main automation script
│   requirements.txt            # Python dependencies
│   run_downloader.bat          # Windows runner script
│   run_downloader.cmd          # Alternative startup script
│   tasklog.txt                 # Log of completed downloads (if used)
│
└── logs/
    └── web driver logs...
```

## Requirements

* Python 3.7+
* Google Chrome or Chromium Browser
* ChromeDriver (managed automatically if using webdriver-manager)

## Installation

1. Clone the repository:

```
git clone https://github.com/AMMorsy/Selenium.git
cd Selenium
```

2. Create and activate a virtual environment (recommended):

```
python -m venv venv
venv\Scripts\activate   # Windows
source venv/bin/activate # Linux/Mac
```

3. Install dependencies:

```
pip install -r requirements.txt
```

## Usage

Tune your actual data,
Run the script normally:

```
python downloader_selenium.py
```

Or use the provided runner script (Windows):

```
run_downloader.bat
```

## Configuration

Adjust pacing, logging, and download behavior directly inside the script's configuration section. Common parameters include:

* Delay ranges
* Retry attempts
* Output directories
* User-agent customization

## Notes

* The script is intended for responsible and legitimate use only.
* Ensure that automated access complies with the legal and usage policies of the target platform.

## License

This project is licensed for personal and educational use.

---

For improvements, optimizations, or custom automation workflows, feel free to modify and adapt the script as needed.

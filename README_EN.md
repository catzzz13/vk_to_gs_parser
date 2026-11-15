# VK Parser 🤖

A fast and robust VKontakte (VK) parser designed to automate the grading and verification of tasks. The application searches for specific topics in a VK group, extracts comments, applies smart filtering (detecting late submissions and copied answers), and exports the processed data to Excel and Google Sheets.

**Author:** [baunchik](https://vk.ru/baunchik)

## 🚀 Features
- **Smart Topic Filtering:** Automatically finds topics containing the word "task" (задание) and your specific team name.
- **Automated Flags:** 
  - `ВРЕМЯ` (LATE): Automatically marks comments submitted more than 36 hours after the linked post's publication.
  - `ЧИТОР` (CHEATER): Detects and flags duplicate/copy-pasted comments.
- **Data Export:**
  - **Excel:** Generates an `.xlsx` file with a separate worksheet for each task.
  - **Google Sheets:** Automatically pushes data into a specified Google Spreadsheet.
- **Performance Optimized:** Built in Rust with asynchronous requests, rate-limiting, and user-caching (to save VK API limits).
- **Easy Installer:** A Python script that automatically sets up the entire Rust environment and compiles the release build.

## 📦 Installation

### Prerequisites
- **Python 3.8+** (for the installer)
- **Rust** (the installer can automatically download and set up Rust if it's missing)

### Quick Start
1. Clone this repository or download the source code.
2. Open your terminal in the project directory and run:
   ```bash
   python install.py
# VK Parser — Complete Guide

> [!NOTE]
> **What is this program and how does it work?**
> This is a smart parser designed to automate the grading and verification of tasks. The program scans the specified VKontakte group, finds topics (discussions) related to your team, downloads all comments, cleans them from junk, and neatly exports them into an Excel file and/or Google Spreadsheet.
> 
> **Code features:**
> - The program is protected against VKontakte rate limits (built-in "smart rate limiter").
> - It caches user names: if you run it twice within 24 hours, it won't waste time re-downloading names from VK.
> - The author's name is displayed in the console at startup.

## Table of Contents
1. [VK API Setup (Token)](#1-vk-api-setup-token)
2. [Google Sheets Setup (Optional)](#2-google-sheets-setup-optional)
3. [Configuration (settings.json)](#3-configuration-settingsjson)
4. [Flags and Filtering Logic](#4-flags-and-filtering-logic)
5. [Export Structure (Excel and Sheets)](#5-export-structure-excel-and-sheets)
6. [Launch and Example of Successful Execution](#6-launch-and-example-of-successful-execution)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. VK API Setup (Token)
To read comments, the program needs a digital pass — a **Token**.

### How to get a token?
1. Go to the website [vkhost.github.io](https://vkhost.github.io/).
2. Select the **Kate Mobile** application.
3. Click "Get Token". You will be redirected to VK, where you need to grant access. *Important: The program requests `wall`, `groups`, and `offline` permissions. The `offline` permission is crucial; otherwise, the token will expire in an hour.*
4. After authorization, copy the long string from your browser's address bar (it starts with `vk1.a...`).

### Where to insert it?
Open the `vk-parser/token.txt` file (with Notepad) and paste the token there. Remove all extra characters and comments so that **only one line with the token** remains in the file.

---

## 2. Google Sheets Setup (Optional)
If you want the data to automatically flow into a Google Spreadsheet, you need to create a "robot" (Service Account).

### Creating a robot in Google Cloud
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. In the "Library" section, find and enable the **Google Sheets API** and **Google Drive API**.
3. In the "IAM & Admin" -> "Service Accounts" section, create an account.
4. In this account, click "Manage Keys" -> "Create new key" -> select **JSON**. A file will be downloaded.
5. Rename this file to `credentials.json` and place it in the `vk-parser` folder (replacing the template).

> [!IMPORTANT]
> **Most important! Do not miss this!**
> 1. Open your `credentials.json` and find the address in the `"client_email"` field. Copy it.
> 2. Open your Google Spreadsheet and click the **"Share"** button.
> 3. Paste the copied robot address and give it **"Editor"** rights. Without this, the program will not be able to write data.

---

## 3. Configuration (settings.json)
The `settings.json` file is the brain of the program. Open it with Notepad.

```json
{
  "group_id": 233578280,
  "team_name": "Канониры Пеликана",
  "spreadsheet": "My Spreadsheet",
  "worksheet": "Sheet1",
  "credentials": "credentials.json",
  "output": "output",
  "max_comments_per_topic": 10000,
  "requests_per_second": 3
}
```

*   `group_id`: VK group ID (numbers only).
*   `team_name`: Your team's name. The program searches for topics containing the word "задание" (task) and this name. *(Note: The parser is hardcoded to search for the Russian word "задание").*
*   `spreadsheet`: The exact name of the Google Spreadsheet (no links, just the name).
*   `worksheet`: The name of the sheet inside this spreadsheet (e.g., "Sheet1").
*   `requests_per_second`: Speed. The VK limit is 3 requests per second. Leave it as `3`.

---

## 4. Flags and Filtering Logic
The program doesn't just copy everything blindly; it analyzes the text.
*   **Junk filtering:** Comments from communities (not real people) and empty messages do not make it into the final table.

> [!WARNING]  
> **Flag "ВРЕМЯ" (LATE)**
> If a user leaves a comment with a link to a post (like `vk.com/wall-123_456`), the program checks the post's publication date. If the comment was written **later than 36 hours** after the post was published, the flag `ВРЕМЯ` is added to the beginning of the text.
> *Why:* You can instantly see who submitted the task late.

> [!WARNING]  
> **Flag "ЧИТОР" (CHEATER)**
> The program compares the text of comments within a single task. If someone copied another person's answer (the text matches 100% case-insensitively), the flag `ЧИТОР` is added to the beginning.
> *Why:* Instantly identifies copy-pasted answers.

---

## 5. Export Structure (Excel and Sheets)

### Excel
The file is created in the `output` folder and is named `GroupName_Date.xlsx`. Each task is exported to a **separate worksheet** (tab). Columns:
*   **A: ID** — User ID.
*   **B: Mention** — tag `[id123|Name]`.
*   **C: Name** — First and last name.
*   **D: Profile** — Link to the page.
*   **E: Comment** — Text (with "ВРЕМЯ" or "ЧИТОР" flags if applicable).
*   **F: Time** — Date and time of submission.

### Google Sheets
Data is written in blocks, starting from column **D** (the first row is reserved for your headers):
*   Columns D, F, H, etc. — Profile links.
*   Columns E, G, I, etc. — Comment texts.
*   Tasks are automatically sorted by number (the program looks for the pattern "Задание N").

---

## 6. Launch and Example of Successful Execution
To launch, simply open the `run.bat` file in the `vk-parser` folder.

### What an ideal launch looks like
Here is an example of a real log. Note that the program collected the data in 1 minute, saved the Excel file, and uploaded the data to Google Sheets.

```text
[INFO] [09:08:17] vk_parser: Group ID: 233578280
[INFO] [09:08:17] vk_parser: Team: Канониры Пеликана
[INFO] [09:08:17] vk_parser::user_cache: Loaded 257 cached users
[INFO] [09:08:17] vk_parser::parser: Group: Голландец 111125
[INFO] [09:08:17] vk_parser::parser: Total topics: 28
[INFO] [09:08:17] vk_parser::parser: Matching topics for 'Канониры Пеликана': 7
[INFO] [09:08:17] vk_parser::parser: [1/7] Канониры Пеликана. Задание за зелен
[INFO] [09:08:17] vk_parser::parser:   -> 30 comments
[INFO] [09:08:17] vk_parser::parser: [2/7] Канониры Пеликана. Задание за отзыв
[INFO] [09:08:17] vk_parser::parser:   -> 54 comments
[INFO] [09:08:17] vk_parser::parser: [3/7] Канониры Пеликана. Задание №3
[INFO] [09:08:17] vk_parser::parser:   -> 201 comments
[INFO] [09:08:17] vk_parser::parser: [4/7] Канониры Пеликана. Задание №5
[INFO] [09:08:17] vk_parser::parser:   -> 180 comments
[INFO] [09:08:17] vk_parser::parser: [5/7] Канониры Пеликана. Задание №4
[INFO] [09:08:17] vk_parser::parser:   -> 197 comments
[INFO] [09:08:17] vk_parser::parser: [6/7] Канониры Пеликана. Задание №2
[INFO] [09:08:17] vk_parser::parser:   -> 214 comments
[INFO] [09:08:17] vk_parser::parser: [7/7] Канониры Пеликана. Задание №1
[INFO] [09:08:17] vk_parser::parser:   -> 237 comments
[INFO] [09:08:17] vk_parser: Total: 7 topics, 1113 comments
[INFO] [09:08:17] vk_parser: Excel: output\Голландец 111125_2026-11-15.xlsx
[WARN] [09:08:17] vk_parser::gsheets: Not enough columns for 'Канониры Пеликана. Задание за отзыв'
[INFO] [09:08:17] vk_parser::gsheets: 2118 values written to Sheets
Press any key to continue . . .
```

> [!NOTE]
> **Why did the warning (WARN) appear?**
> This is **not an error**. There is a limit in the program's code: it writes data to Google Sheets only up to the 14th column (column N). Since you have 7 tasks, and each task takes up 2 columns (starting from D), the program simply couldn't fit the last task into the limit and skipped it *only in the Google Spreadsheet*. **All 7 tasks** were exported to the Excel file without restrictions.

---

## 7. Troubleshooting

> [!CAUTION]
> **Error: `Sheets connection: Table '' not found`**
> **Solution:** Check that the `spreadsheet` field in `settings.json` contains the exact table name, and that you have given "Editor" rights to the robot from `credentials.json`.

> [!CAUTION]
> **Error: `VK API error [5]: User authorization failed`**
> **Solution:** The token in `token.txt` is invalid or expired. Generate a new one (make sure to include the `offline` permission).

> [!CAUTION]
> **Error: `VK API error [6]: Too many requests per second`**
> **Solution:** You have exceeded the VK request limit. The program will automatically wait and continue, but to prevent this, make sure `settings.json` has `"requests_per_second": 3`.

> [!NOTE]
> **The program "hangs" and prints nothing to the console**
> **Reason:** It is checking post links to apply the "ВРЕМЯ" (LATE) flag. If there are hundreds of links in the comments, this requires many requests. Just wait 1–2 minutes; it will finish. *(We have already removed artificial delays in the code, so this only happens with a massive number of unique post links).*

---
*VK Parser FAQ © 2026. Authorship belongs to [https://vk.ru/baunchik](https://vk.ru/baunchik).*

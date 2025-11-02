# COSC 448 – GitHub Data Pipeline

### 📄 Overview

This project implements a **unified data ingestion pipeline** that collects and links repository-level data from the **GitHub REST API (v3)**.  
It was built as part of the **COSC 448 Directed Studies (Mining Digital Work Artifacts)** course at **UBC Okanagan**.

### ⚙️ Features

- Retrieves:
  - Repository metadata (`repo_meta.json`)
  - Issues (`issues.json`)
  - Pull Requests (`pull_requests.json`)
  - Commits (`commits.json`)
- Derives analytical relationships:
  - PRs linked to issues (`prs_with_linked_issues.json`)
  - Issues closed by commits (`issues_closed_by_commits.json`)
  - Cross-repo references (`cross_repo_links.json`)
- Adds a universal `repo_name` to every entry for traceability.
- Includes retry logic, exponential backoff, and token rotation for reliability.

### 📁 Output Structure

Each processed repo produces:

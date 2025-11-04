# COSC 448 – GitHub Data Pipeline

## Overview

This repository contains the implementation of a modular and extensible **data pipeline for mining GitHub repositories**. The goal of this project is to automate the end-to-end retrieval, processing, and indexing of repository data to support software analytics research.  

Developed as part of **COSC 448 (Direct Studies: Development and Deployment of a Scalable Data Pipeline for Research)** at **UBC Okanagan**, this project demonstrates the application of core software engineering principles such as modular design, testing, validation, and documentation. It also aligns with the course outcomes by emphasizing scalable data engineering workflows using **GitHub REST APIs (v3)**, **Elasticsearch**, and modern Python development practices.

The system was built to collect and analyze open-source software data in a reproducible and extensible way, following the same objectives outlined in the course syllabus — namely:  
- Automate the collection and enrichment of software repository data  
- Apply engineering best practices for maintainability and reliability  
- Enable indexing, search, and visualization of collected data through Elasticsearch and Kibana  

---

## Objectives

The objectives of this project directly reflect the **learning outcomes** of COSC 448:

1. **Design and implementation of a modular data pipeline** for software analytics.  
2. **Automation of data collection** from GitHub repositories using authenticated REST API calls.  
3. **Integration of scalable storage and indexing** through Elasticsearch.  
4. **Testing and validation** to ensure data reliability and code quality.  
5. **Comprehensive documentation** to support reproducibility and transparency.  

---

## Requirements

**Software:**
- Python 3.10+
- Docker
- Elasticsearch 8.x (local or remote)
- GitHub Personal Access Token (with read access to public repositories)

All dependencies can be installed via:
```bash
pip install -r requirements.txt
```

---

## Setup and Execution

Below is the full process for retrieving, ingesting, and indexing the GitHub data into a local ElasticSearch database. This sequence ensures that the system is configured correctly and that all required services are running before data ingestion.

### Before You Start

1. Add your GitHub API token(s) inside `rest_pipeline.py`.  
   This token is used for authenticated access to the GitHub REST API and prevents rate limiting.

2. Set your Elasticsearch authorization inside `index_elasticsearch.py`.  
   Provide the username, password, API, and URL for your local or hosted Elasticsearch instance.

---

### Steps

#### 1. Clone the repository
```bash
git clone https://github.com/abijeet-dhillon/github_data_pipeline.git
cd github_data_pipeline
```

#### 2. Open Docker
Ensure Docker Desktop (or an equivalent daemon) is running before starting containers.

#### 3. Activate the virtual environment
```bash
source venv/bin/activate
```

#### 4. Retrieve GitHub data
Run the following command to collect all repository data:
```bash
python3 v3_data_retrieval.py
```
Inside this file:
- Enter your GitHub tokens in the `GITHUB_TOKENS` list.  
- Specify the repositories you want to retrieve, e.g., `owner/repo`.  
- The script will fetch metadata, issues, pull requests, commits, and cross-references.  

Note: Depending on the size of the repositories, data retrieval time may vary. Please wait for data retrieval to finish before moving onto the next step.

#### 5. Start local Elasticsearch in Docker
From the project directory:
```bash
cd elastic-start-local
docker compose up -d
```
Alternatively, you may run your own Elasticsearch instance manually or via Docker Hub:
```bash
docker run -d --name elasticsearch -p 9200:9200 -e "discovery.type=single-node" elasticsearch:8.15.0
```

#### 6. Index data into Elasticsearch
Once data collection is complete:
```bash
python3 rest_elasticsearch.py
```
This script ingests all JSON files under `/output/` and indexes them into your configured Elasticsearch instance.  
It automatically detects and processes each document type while ensuring schema consistency.

#### 7. Verify data in Kibana
Access Kibana at [http://localhost:5601](http://localhost:5601) or through your preferred analytics interface.  
You can search and visualize data using indices such as `github_data_*`.

#### 8. Shut everything down
When finished, stop and remove the containers:
```bash
cd elastic-start-local
docker compose down
```

---

## Testing

The repository includes a comprehensive test suite, ensuring that all major components (API handling, pagination, error logging, and file generation) are validated.

Run the tests with:
```bash
pytest -v --cov=rest_pipeline --cov-report=term-missing
```

---

## Code Quality and Documentation

This project follows the software engineering standards outlined in the COSC 448 syllabus:
- All scripts are fully documented with descriptive docstrings and inline comments. 
- Functions and modules follow PEP 8 style guidelines for readability.  
- Testing and logging are integrated throughout for reliability and traceability.  
- GitHub issues and pull requests are used to record progress, with clear summaries and rationales for each update.  

By maintaining clear documentation, consistent naming, and structured commits, the project meets the expectations for professional, research-grade code in a collaborative academic setting.

---

## Authors

**Abijeet Dhillon**  
UBC Okanagan – COSC 448: Direct Studies  
Instructor: Dr. Gema Rodríguez-Pérez  
Email: gema.rodriguezperez@ubc.ca

---

## License

This repository is available for educational and research purposes under the MIT License.

#!/bin/bash
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/python3 -m streamlit run app.py --server.port 8501 --server.headless true

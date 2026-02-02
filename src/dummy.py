# dummy.py - A test file with non-standard imports for dependency detection

import requests
from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.stats as stats
import django # Example of a larger framework import
import flask # Another web framework
import sqlalchemy # ORM library
import faker # For generating fake data

def fetch_data(url):
    """Fetches data from a URL using requests."""
    response = requests.get(url)
    return response.text

def parse_html(html_content):
    """Parses HTML content using BeautifulSoup."""
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.title.string if soup.title else "No title"

def analyze_data(data):
    """Performs some data analysis using numpy and pandas."""
    df = pd.DataFrame(data)
    mean_val = np.mean(df['value'])
    std_dev = np.std(df['value'])
    return {"mean": mean_val, "std_dev": std_dev}

def generate_fake_user():
    """Generates fake user data using Faker."""
    from faker import Faker
    fake = Faker()
    return {
        "name": fake.name(),
        "address": fake.address(),
        "email": fake.email()
    }

if __name__ == "__main__":
    print("Running dummy checks...")
    # Example usage (these lines won't affect dependency detection, but show context)
    # try:
    #     html = fetch_data("https://www.example.com")
    #     print(f"Page title: {parse_html(html)}")
    # except Exception as e:
    #     print(f"Could not fetch/parse: {e}")

    # dummy_data = {'value': [10, 20, 30, 40, 50]}
    # analysis_result = analyze_data(dummy_data)
    # print(f"Analysis: {analysis_result}")

    # user = generate_fake_user()
    # print(f"Fake user: {user['name']}, {user['email']}")

    print("Dummy checks complete.")


from flask import Flask, render_template, request, Response
from bs4 import BeautifulSoup
from collections import Counter
from urllib.parse import urlparse
import requests
import pandas as pd
import io
import re
import ipaddress
import socket

app = Flask(__name__)

# Common words that we do not need to count as keywords
STOP_WORDS = set("""
the a an and or but is are was were be been being to of in on for
with by from this that it as at we you your our they their i he she
not have has had do does did will would can could about into than
then so if its also more most such these those page website
""".split())


# Validate the URL before accessing it
def validate_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a valid HTTP or HTTPS webpage URL.")

    host = parsed.hostname.lower()

    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Local URLs are not allowed.")

    try:
        addresses = socket.getaddrinfo(host, None)

        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])

            if not ip.is_global:
                raise ValueError(
                    "Private or local network URLs are not allowed."
                )

    except socket.gaierror:
        raise ValueError("Could not resolve the website address.")


# Extract and analyze webpage content
def analyze_page(url):
    validate_url(url)

    headers = {
        "User-Agent": "StudentWebContentAnalytics/1.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=12,
        stream=True,
        allow_redirects=False
    )

    try:
        # Handle redirects
        if response.status_code in (301, 302, 303, 307, 308):
            raise ValueError(
                "This page redirects. Try its final URL directly."
            )

        response.raise_for_status()

        # Check that the URL points to an HTML page
        content_type = response.headers.get("Content-Type", "")

        if "text/html" not in content_type.lower():
            raise ValueError(
                "The URL must point to an HTML webpage."
            )

        # Limit downloaded content to 2 MB
        chunks = []
        total = 0

        for chunk in response.iter_content(chunk_size=8192):
            total += len(chunk)

            if total > 2_000_000:
                raise ValueError(
                    "The webpage is too large to analyze (2 MB limit)."
                )

            chunks.append(chunk)

        html = b"".join(chunks)

    finally:
        response.close()

    # Parse HTML content
    soup = BeautifulSoup(html, "html.parser")

    # Extract the webpage title
    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else "No title found"
    )

    # Remove unwanted HTML elements
    for element in soup([
        "script", "style", "nav", "footer",
        "header", "noscript", "svg", "iframe"
    ]):
        element.decompose()

    # Prefer the main content or article
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    # Extract readable text
    text = main.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        raise ValueError(
            "No readable text was found on this page."
        )

    # Count words
    words = re.findall(
        r"\b[a-zA-Z0-9'-]+\b",
        text.lower()
    )

    # Count sentences
    sentences = [
        sentence
        for sentence in re.split(r"[.!?]+", text)
        if sentence.strip()
    ]

    # Count paragraphs
    paragraphs = [
        paragraph.get_text(" ", strip=True)
        for paragraph in main.find_all("p")
        if paragraph.get_text(" ", strip=True)
    ]

    # Find the ten most frequent meaningful keywords
    raw_keywords = Counter(
        word
        for word in words
        if len(word) > 2 and word not in STOP_WORDS
    ).most_common(10)

    # Calculate the maximum frequency for the keyword bars
    max_count = (
        raw_keywords[0][1]
        if raw_keywords
        else 1
    )

    # Prepare keywords and bar percentages
    keywords = [
        {
            "word": word,
            "count": count,
            "percentage": round(
                count * 100 / max_count, 2
            )
        }
        for word, count in raw_keywords
    ]

    # Return all analysis results
    return {
        "url": url,
        "title": title,
        "text": text,
        "word_count": len(words),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "unique_words": len(set(words)),
        "keywords": keywords,
        "preview": text[:1200]
    }


# Home page and webpage analysis
@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        url = request.form.get("url", "").strip()

        try:
            result = analyze_page(url)

        except (
            ValueError,
            requests.RequestException
        ) as exc:
            error = str(exc) or "Unable to fetch this webpage."

    return render_template(
        "index.html",
        result=result,
        error=error
    )


# Download the analysis results as a CSV file
@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url", "").strip()

    try:
        result = analyze_page(url)

        output = io.StringIO()

        data = pd.DataFrame([{
            "URL": result["url"],
            "Page Title": result["title"],
            "Word Count": result["word_count"],
            "Sentence Count": result["sentence_count"],
            "Paragraph Count": result["paragraph_count"],
            "Unique Words": result["unique_words"],
            "Top Keywords": ", ".join(
                f"{item['word']} ({item['count']})"
                for item in result["keywords"]
            )
        }])

        data.to_csv(output, index=False)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                "attachment; filename=web_analysis.csv"
            }
        )

    except (
        ValueError,
        requests.RequestException
    ) as exc:
        return str(exc), 400


# Start the Flask application
if __name__ == "__main__":
    app.run(debug=True)

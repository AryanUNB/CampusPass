
# CampusPass – Student Bus Pass Security

CS 2413 – Information Security | Fall 2026  
University of New Brunswick | Team 13

## Team Members
- Aryan Bansal
- Daniel Bradbury
- Dhruv Manishbhai Thumar
- Hadi Akbar

## Project Overview

CampusPass is an educational web application demonstrating
authentication and authorization vulnerabilities in a fictional
student bus-pass system.

The project compares an intentionally vulnerable implementation
with an improved version containing security controls.

## Security Vulnerabilities

The original system allows users to:
- Submit arbitrary student numbers.
- Claim bus passes without proving student ownership.
- Discover valid or already-claimed student numbers.
- Repeatedly guess student numbers without restrictions.

## Implemented Security Controls

- Password authentication using hashed credentials.
- Server-side student identity verification.
- Authorization checks linking accounts to student numbers.
- Generic error messages to reduce information disclosure.
- IP-based rate limiting after five failed attempts.
- Ten-minute temporary blocking.
- Recovery of previously unverified bus-pass claims.

## Technologies

- Python
- Flask
- SQLite
- HTML and CSS
- Werkzeug password hashing

## Installation

Install dependencies:

    py -m pip install -r requirements.txt

Start the application:

    py app.py

Open http://127.0.0.1:5000

## Security Testing

1. Unauthorized bus-pass claim in the vulnerable version.
2. Legitimate student blocked after unauthorized claim.
3. Unauthorized claim rejected by the secured version.
4. Legitimate student successfully recovers their pass.
5. Repeated invalid attempts trigger temporary blocking.

## Limitations

This is a local educational simulation, not a production system.

University authentication is simulated using fictional accounts.
No actual university identity provider is connected.

Rate limiting is IP-based and is intended for demonstration.
Additional protections would be necessary for production use.

## GitHub Repository

https://github.com/AryanUNB/CampusPass

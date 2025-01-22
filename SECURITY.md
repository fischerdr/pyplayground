# Security Policy

## Supported Versions

This project supports Python versions from 3.9 to 3.14. We actively maintain and provide security updates for these versions.

| Python Version | Supported          |
| -------------- | ------------------ |
| 3.14.x         | :white_check_mark: |
| 3.13.x         | :white_check_mark: |
| 3.12.x         | :white_check_mark: |
| 3.11.x         | :white_check_mark: |
| 3.10.x         | :white_check_mark: |
| 3.9.x          | :white_check_mark: |
| < 3.9          | :x:                |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security vulnerability within this project, please follow these steps:

1. **Do Not** create a public GitHub issue for the vulnerability.
2. Send a detailed report to [SECURITY_EMAIL] (Please contact repository maintainers for the correct email address).
3. Include the following in your report:
   - Description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact
   - Suggested fix (if possible)

### What to expect

- You will receive an acknowledgment of your report within 48 hours.
- We will investigate and provide regular updates on the progress.
- Once the vulnerability is confirmed, we will work on a fix.
- After the fix is ready, we will release a security update.

## Security Best Practices

This project follows these security best practices:

1. **Dependency Management**
   - Regular dependency updates and security audits
   - Automated dependency scanning for vulnerabilities
   - Strict version pinning in requirements files

2. **Code Security**
   - Static code analysis using flake8
   - Type checking with mypy
   - Automated testing with pytest
   - Code formatting with black

3. **Environment Security**
   - Use of environment variables for sensitive configuration
   - Double quotes for environment variable values
   - Secure handling of API keys and credentials
   - Logging security events to dedicated log files

4. **API Security**
   - Secure mocking of K8s, VMware, and Vault APIs
   - Input validation and sanitization
   - Proper error handling and logging

5. **Documentation**
   - Security-related documentation maintained in docs/ directory
   - Regular documentation updates with code changes
   - Clear documentation of security-related configurations

## Security Measures

1. **Authentication & Authorization**
   - Proper credential management
   - Secure token handling
   - Role-based access control where applicable

2. **Data Protection**
   - Secure handling of sensitive data
   - Proper logging practices (no sensitive data in logs)
   - Secure configuration management

3. **Infrastructure Security**
   - Container security best practices for Docker (CentOS/Fedora/Alpine)
   - Kubernetes security configurations
   - Vault security best practices

## Compliance

Please ensure any contributions to this project follow:
- Python security best practices
- Project-specific security guidelines
- Relevant compliance requirements for K8s, VMware, and Vault integrations

## Security Updates

Security updates and patches will be released as soon as possible after a vulnerability is confirmed and fixed. Updates will be distributed through:
1. GitHub releases
2. Updated package versions
3. Security advisories when applicable

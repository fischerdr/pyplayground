# Markdown Documentation Standards

This document defines the markdown standards and linting rules for documentation in this project.

## Markdown Linting

**CRITICAL**: All markdown files must pass linting before committing.

### Running the Linter

```bash
# Lint all markdown files (MD013 line length check is disabled)
pymarkdownlnt -d MD013 scan

# Lint specific file
pymarkdownlnt -d MD013 scan README.md

# Lint all markdown in docs/
pymarkdownlnt -d MD013 scan docs/

# Lint with verbose output
pymarkdownlnt -d MD013 -x-log-level=DEBUG scan
```

### Markdown Standards

- **MD013 (line length)**: Disabled - long lines are acceptable in documentation
- **MD040 (code block language)**: REQUIRED - all fenced code blocks must specify a language (see "Code Block Language Specification" section below)
- **Professional tone**: No emojis or icons in documentation
- All other pymarkdownlnt rules must pass

## Code Block Language Specification

**Rule**: All fenced code blocks MUST have a language identifier specified to comply with MD040/fenced-code-language linting rules.

### Requirements

- Every code block using triple backticks (```) MUST include a language identifier
- If no specific language applies, use `text` as the default language identifier
- Never create code blocks with opening ``` without a language specifier

### Examples

**Correct**:

```python
print("Hello World")
```

```bash
echo "Hello World"
```

```text
This is plain text content
No specific language applies
```

**Incorrect** (do not use):

Using triple backticks (```) without a language identifier violates MD040 and is not allowed.

### Common Language Identifiers

- Programming: `python`, `bash`, `javascript`, `java`, `yaml`, `json`, `xml`
- Output/Logs: `text`, `console`, `log`
- Documentation: `markdown`, `html`, `css`
- Configuration: `ini`, `toml`, `conf`
- When in doubt: `text`

## Documentation Style Guidelines

**CRITICAL**: Follow these rules when working with documentation:

### Professional Tone

- **No emojis or icons** - Documentation must be professional and text-only
- Use clear, concise language
- Focus on technical accuracy and completeness

### IMPORTANT: When to Create Documentation

- Ask for approval before generating or modifying documentation files
- Never proactively create README files or documentation without explicit request
- Update documentation when making code changes that affect user-facing behavior

### Documentation Organization

- Keep documentation in a dedicated `docs/` directory when possible
- Use descriptive filenames (e.g., `INSTALLATION.md`, `API_REFERENCE.md`)
- Create a table of contents for longer documents
- Use relative links for cross-referencing other documentation files

### Formatting Standards

- Use ATX-style headers (`#` prefix) rather than Setext-style underlines
- Use reference-style links for URLs used multiple times
- Keep lists consistent (all bullets or all numbers, not mixed)
- Use code blocks for commands, code samples, and configuration examples
- Use inline code (backticks) for:
  - File names: `README.md`
  - Directory paths: `src/components/`
  - Function/class names: `parseData()`
  - Configuration keys: `line-length`
  - Command-line flags: `--version`

### Content Guidelines

- Write in present tense for current behavior
- Use imperative mood for instructions ("Run the command", not "You should run the command")
- Include examples for complex concepts
- Document both what works and what doesn't (common pitfalls)
- Keep paragraphs focused on a single topic

## Integration with pymarkdownlnt

### Installation

```bash
# Install via pip
pip install pymarkdownlnt

# Or in a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
pip install pymarkdownlnt
```

### Configuration

You can create a `.pymarkdown.json` configuration file in your project root:

```json
{
  "plugins": {
    "line-length": {
      "enabled": false
    }
  }
}
```

Or disable rules via command-line as shown in the examples above using `-d MD013`.

### Pre-commit Integration

Add to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/jackdewinter/pymarkdown
  rev: v0.9.14
  hooks:
    - id: pymarkdown
      args: ["-d", "MD013", "scan"]
```

## Enforcement

- All markdown files must pass `pymarkdownlnt -d MD013 scan` before merging
- CI/CD pipelines should include markdown linting checks
- Reviewers should verify markdown quality during code review
- Fix linting issues in the same commit as the content changes

## Resources

- [pymarkdownlnt Documentation](https://github.com/jackdewinter/pymarkdown)
- [Markdown Guide](https://www.markdownguide.org/)
- [CommonMark Specification](https://commonmark.org/)

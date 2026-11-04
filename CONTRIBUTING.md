# Contributing to NREL-shift

Thank you for your interest in contributing to NREL-shift! This document provides guidelines and instructions for contributing.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

## Getting Started

### Prerequisites

- Python >= 3.11
- Git
- Familiarity with power distribution systems is helpful but not required

### Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/YOUR_USERNAME/shift.git
   cd shift
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Development Dependencies**
   ```bash
   pip install -e ".[dev,doc]"
   ```

4. **Install Pre-commit Hooks**
   ```bash
   pre-commit install
   ```

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

Use descriptive branch names:
- `feature/` for new features
- `fix/` for bug fixes
- `docs/` for documentation updates
- `test/` for test additions/modifications

### 2. Make Your Changes

- Write clean, readable code
- Follow the existing code style
- Add docstrings to all public functions, classes, and methods
- Update documentation as needed

### 3. Add Tests

All new functionality should include tests:

```python
def test_your_new_feature():
    """Test description following Google style."""
    # Arrange
    input_data = ...
    
    # Act
    result = your_function(input_data)
    
    # Assert
    assert result == expected_output
```

### 4. Run Tests and Linting

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=shift --cov-report=html

# Run linter
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format code
ruff format .
```

### 5. Commit Your Changes

Write clear, descriptive commit messages:

```bash
git add .
git commit -m "Add feature: brief description

Detailed explanation of changes if needed.
Relates to #issue-number"
```

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear title describing the change
- Description of what changed and why
- Reference to related issues
- Screenshots for UI changes (if applicable)

## Code Style Guidelines

### Python Style

We follow PEP 8 with some modifications enforced by Ruff:

- Line length: 99 characters
- Use double quotes for strings
- Use type hints for function parameters and returns
- Use descriptive variable names

### Docstring Format

Use NumPy-style docstrings:

```python
def function_name(param1: str, param2: int) -> bool:
    """Brief one-line description of the function.

    Longer description if needed, explaining the purpose
    and behavior of the function.

    Parameters
    ----------
    param1 : str
        Description of param1.
    param2 : int
        Description of param2.

    Returns
    -------
    bool
        Description of return value.

    Raises
    ------
    ValueError
        When invalid input is provided.

    Examples
    --------
    >>> function_name("test", 5)
    True
    """
```

### Type Hints

Use type hints throughout:

```python
from typing import Optional

def process_data(
    data: list[float],
    config: Optional[dict[str, str]] = None,
) -> dict[str, float]:
    """Process data with optional configuration."""
```

## Testing Guidelines

### Test Organization

- Place tests in the `tests/` directory
- Name test files `test_<module>.py`
- Name test functions `test_<functionality>`
- Use fixtures for common setup

### Test Coverage

- Aim for > 80% code coverage on new code
- Test both success and failure cases
- Test edge cases and boundary conditions
- Use parametrized tests for multiple scenarios

Example:

```python
import pytest
from shift import DistributionGraph, NodeModel
from infrasys import Location

@pytest.fixture
def sample_graph():
    """Fixture providing a graph with one node."""
    graph = DistributionGraph()
    graph.add_node(NodeModel(name="n1", location=Location(x=-97.3, y=32.7)))
    return graph

@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_function_with_multiple_inputs(input, expected):
    """Test function with various inputs."""
    assert function(input) == expected
```

## Documentation

### Updating Documentation

- Update docstrings when changing function signatures
- Update usage guides in `docs/usage/` for new features
- Update reference docs in `docs/references/` for API changes
- Add examples to demonstrate new functionality

### Building Documentation Locally

```bash
cd docs
make html
```

View the documentation at `docs/_build/html/index.html`

## Pull Request Process

1. **Ensure CI Passes**: All tests and checks must pass
2. **Update Documentation**: Include relevant documentation updates
3. **Add Tests**: New features require test coverage
4. **Update CHANGELOG**: Add entry describing your changes
5. **Request Review**: Tag appropriate reviewers
6. **Address Feedback**: Respond to review comments promptly
7. **Squash Commits**: Clean up commit history if requested

### PR Checklist

- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] Code follows style guidelines
- [ ] No new linting errors
- [ ] CHANGELOG.md updated
- [ ] Commits are clear and descriptive

## Reporting Issues

### Bug Reports

Include:
- Clear, descriptive title
- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
- Relevant code snippets or error messages
- Minimal reproducible example

### Feature Requests

Include:
- Clear description of the proposed feature
- Use cases and motivation
- Example API or usage pattern
- Potential implementation approach

## Questions and Support

- **Issues**: Use [GitHub Issues](https://github.com/NLR-Distribution-Suite/shift/issues) for bugs and feature requests
- **Discussions**: Use [GitHub Discussions](https://github.com/NLR-Distribution-Suite/shift/discussions) for questions
- **Email**: Contact maintainers for sensitive issues

## License

By contributing, you agree that your contributions will be licensed under the BSD-3-Clause License.

## Recognition

Contributors will be recognized in:
- CHANGELOG.md for their contributions
- Project documentation
- Release notes

Thank you for contributing to NREL-shift!

# PDF Dark Mode

A Python tool for converting PDFs to dark mode by inverting colors and handling font fallbacks.

## Features

- Inverts PDF colors to create a dark mode version
- Handles font fallbacks for missing fonts
- Preserves text formatting and styles
- Processes tables and borders
- Supports various PDF elements including text, images, and drawings

## Requirements

- Python 3.6+
- PyMuPDF (fitz)
- logging
- os
- sys

## Installation

1. Clone the repository:
```bash
git clone https://github.com/FurkaanBoraa/PDFDarkMode.git
cd PDFDarkMode
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Place your PDF file in the project directory
2. Run the script:
```bash
python test_processor.py
```

The script will create an output file with the prefix "output_" followed by the original filename.

## Configuration

The script uses fallback fonts from the Windows Fonts directory by default. You can modify the font paths in `test_processor.py`:

```python
fallback_paths = {
    'regular': 'C:/Windows/Fonts/arial.ttf',
    'bold': 'C:/Windows/Fonts/arialbd.ttf',
    'italic': 'C:/Windows/Fonts/ariali.ttf',
    'bold_italic': 'C:/Windows/Fonts/arialbi.ttf'
}
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- PyMuPDF for PDF processing capabilities
- Windows Fonts for fallback font support 
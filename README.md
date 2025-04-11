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

## Download Executable

For a standalone Windows executable (.exe) that doesn't require Python installation, please check the **[Releases](https://github.com/FurkaanBoraa/PDFDarkMode/releases)** page on GitHub.

Download the `PDFDarkConverter.exe` file from the latest release assets.

## Usage

If running from source code:
1. Place your PDF file in the project directory
2. Run the script:
```bash
python pdf_processor.py # Updated to use the GUI script
```

If using the downloaded executable (`PDFDarkConverter.exe`), simply double-click it to run.

Use the application window to select or drag-and-drop your PDF file.
The converted dark mode PDF will be saved in the same directory as the input file (or the executable, if run standalone) with the prefix `output_`.

## Configuration

When running from source, the script uses fallback fonts from the Windows Fonts directory by default. You can modify the font paths in `pdf_processor.py`.

The standalone executable relies on standard Windows fonts (like Arial) being available on the system where it's run.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- PyMuPDF for PDF processing capabilities
- Windows Fonts for fallback font support 
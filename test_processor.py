import logging
from pdf_processor import convert_pdf_colors

# Configure logging for the test script
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s') # Basic config for root

# Get the specific logger used in pdf_processor.py and set its level
pdf_proc_logger = logging.getLogger('pdf_processor')
pdf_proc_logger.setLevel(logging.DEBUG)

# Get the logger for the current module (__main__)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Keep this logger at INFO if needed

input_pdf = "288638.pdf"
output_pdf = "output_288638.pdf"

# Define paths for different styles of the fallback font (Arial)
# Assumes standard Windows font locations
fallback_fonts = {
    "regular": "C:/Windows/Fonts/arial.ttf",
    "bold": "C:/Windows/Fonts/arialbd.ttf",
    "italic": "C:/Windows/Fonts/ariali.ttf",
    "bold_italic": "C:/Windows/Fonts/arialbi.ttf"
}

# Log which fallback fonts are being used
logger.info(f"Starting PDF conversion for: {input_pdf}")
logger.info(f"Using fallback fonts: {fallback_fonts}")

# Pass the dictionary of fallback font paths
result = convert_pdf_colors(input_pdf, output_pdf, fallback_font_paths=fallback_fonts)

if result is None:
    logger.info(f"Successfully created: {output_pdf}")
else:
    logger.error(f"Failed to convert PDF: {result}") 
import fitz  # PyMuPDF
import logging
import os
from typing import Optional, Dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global cache for loaded fallback fonts {style_key: fitz.Font}
fallback_fonts: Dict[str, Optional[fitz.Font]] = {}

def load_fallback_font(font_path: str, style_key: str) -> Optional[fitz.Font]:
    """Load a fallback font from path or return cached instance."""
    global fallback_fonts
    if style_key in fallback_fonts:
        return fallback_fonts[style_key] # Return cached font or None if loading failed previously

    if font_path and os.path.exists(font_path):
        try:
            # Try loading the font using fitz.Font
            fallback_fonts[style_key] = fitz.Font(fontfile=font_path)
            logger.info(f"Successfully loaded fallback font '{style_key}' from: {font_path}")
        except Exception as e:
            # Log the error
            error_message = f"Failed to load fallback font '{style_key}' from {font_path}: {e}"
            logger.error(error_message)
            fallback_fonts[style_key] = None # Cache failure
    else:
        logger.warning(f"Fallback font file for style '{style_key}' not found or path not provided: {font_path}")
        fallback_fonts[style_key] = None # Cache failure
    return fallback_fonts[style_key]

def get_fallback_font_for_span(span: dict, fallback_paths: Dict[str, str]) -> Optional[tuple[str, fitz.Font]]:
    """Determine the best fallback font style based on span flags AND font name analysis."""
    flags = span["flags"]
    font_name_original = span["font"]

    # --- Determine Style from Flags AND Name --- 
    # Check flags first
    flag_bold = bool(flags & 2) 
    flag_italic = bool(flags & 1)

    # Check name as a secondary indicator (case-insensitive)
    name_lower = font_name_original.lower()
    name_bold = "bold" in name_lower or "-bd" in name_lower
    name_italic = "italic" in name_lower or "oblique" in name_lower or "-it" in name_lower
    
    # Combine flag and name checks - prioritize flags if set, otherwise use name
    is_bold = flag_bold or name_bold
    is_italic = flag_italic or name_italic
    # --- End Style Determination ---

    # Try different style combinations in order of preference
    style_attempts = []
    if is_bold and is_italic:
        style_attempts = ["bold_italic", "bold", "italic", "regular"]
    elif is_bold:
        style_attempts = ["bold", "regular"]
    elif is_italic:
        style_attempts = ["italic", "regular"]
    else:
        style_attempts = ["regular"]
        
    # Try each style in order until we find one that works
    for style_key in style_attempts:
        font_path = fallback_paths.get(style_key)
        if font_path:
            font = load_fallback_font(font_path, style_key)
            if font:
                registration_name = f"Fallback-{style_key}"
                return registration_name, font
    
    logger.warning(f"No suitable fallback font found for original font: {font_name_original}") 
    return None

def convert_pdf_colors(
    input_pdf_path: str,
    output_pdf_path: str,
    fallback_font_paths: Optional[Dict[str, str]] = None
) -> Optional[str]:
    """
    Convert a PDF's text color to white and background to black while preserving layout and non-text elements.

    Args:
        input_pdf_path (str): Path to the input PDF file.
        output_pdf_path (str): Path where the modified PDF will be saved.
        fallback_font_paths (Optional[Dict[str, str]]): Dictionary mapping styles
            ('regular', 'bold', 'italic', 'bold_italic') to TTF font file paths.
            Example: {'regular': 'arial.ttf', 'bold': 'arialbd.ttf', ...}

    Returns:
        Optional[str]: Error message if an error occurs, None if successful.

    This function:
    1. Opens the input PDF.
    2. Creates a new PDF for output.
    3. For each page:
       - Adds a black background layer.
       - Extracts text blocks.
       - Redraws text in white, attempting original font first, then appropriate fallback font if provided.
       - Preserves non-text elements (images).
    4. Saves the modified PDF.
    """
    
    # Clear global font cache at the start of each conversion
    global fallback_fonts
    fallback_fonts.clear()
    logger.debug("Cleared global fallback font cache.")
    
    try:
        # Open the input PDF
        doc = fitz.open(input_pdf_path)

        # Create a new PDF for output
        new_doc = fitz.open()

        # Process each page
        for page_num in range(len(doc)):
            page = doc[page_num]

            # Create a new page in the output document with the same dimensions
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)

            # Add black background
            new_page.draw_rect(new_page.rect, color=(0, 0, 0), fill=(0, 0, 0))

            # --- Process and Redraw Drawings (Attempt to make table lines white) ---
            drawings = page.get_drawings()
            for path in drawings:
                # Check path properties to identify potential table lines/borders
                is_stroked = path.get("stroke_opacity", 1) != 0 and path.get("color") # Has stroke color
                is_filled = path.get("fill_opacity", 1) != 0 and path.get("fill")    # Has fill color
                path_width = path.get("width", 1.0) # Line width, default to 1.0 if None

                # More inclusive heuristics for table borders:
                # 1. Thin stroked paths (likely borders)
                # 2. Filled rectangles (likely table cells)
                # 3. Wider lines that might be table borders
                if (is_stroked and path_width < 3.0) or (is_filled and path.get("items", [])[0][0] == "re"):
                    for item in path["items"]:
                        # Ensure we have a valid width for drawing operations
                        draw_width = max(0.1, float(path_width or 1.0))  # Convert to float and ensure positive
                        
                        if item[0] == "l":  # Line
                            new_page.draw_line(item[1], item[2], color=(1, 1, 1), width=draw_width)
                        elif item[0] == "re":  # Rectangle
                            # For filled rectangles, draw both fill and border in white
                            if is_filled:
                                new_page.draw_rect(item[1], color=(1, 1, 1), fill=(1, 1, 1), width=draw_width)
                            else:
                                new_page.draw_rect(item[1], color=(1, 1, 1), fill=None, width=draw_width)
                        elif item[0] == "c":  # Curve
                            # Draw curves as lines between control points
                            points = item[1]
                            for i in range(len(points) - 1):
                                new_page.draw_line(points[i], points[i+1], color=(1, 1, 1), width=draw_width)
                        elif item[0] == "qu":  # Quad
                            # Draw quads as lines between points
                            points = item[1]
                            for i in range(len(points) - 1):
                                new_page.draw_line(points[i], points[i+1], color=(1, 1, 1), width=draw_width)
                    logger.debug(f"Redrawing path as potential table border: color={path.get('color')}, width={draw_width}, type={path.get('items', [])[0][0] if path.get('items') else 'unknown'}")
                else:
                    logger.debug(f"Skipping path: color={path.get('color')}, width={path_width}, type={path.get('items', [])[0][0] if path.get('items') else 'unknown'}")
            # --- End Drawing Processing ---

            # Get text blocks with flags
            # Moved after drawing processing to ensure text is on top
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

            # Process each text block
            for block in blocks:
                if "lines" in block:  # This is a text block
                    for line in block["lines"]:
                        for span in line["spans"]:
                            # Get the original text and its properties
                            text = span["text"]
                            font_name_original = span["font"]
                            size = span["size"]
                            origin = span["origin"]
                            flags = span["flags"] # Get flags for bold/italic check

                            # Attempt to draw the text in white with the original font
                            try:
                                new_page.insert_text(
                                    point=origin,
                                    text=text,
                                    fontsize=size,
                                    color=(1, 1, 1),  # White color
                                    fontname=font_name_original
                                )
                            except RuntimeError as font_error:
                                fallback_info = None
                                # If original font fails, try to get appropriate fallback style
                                if fallback_font_paths and ("cannot open resource" in str(font_error) or "unknown file format" in str(font_error)):
                                    fallback_info = get_fallback_font_for_span(span, fallback_font_paths)
                                
                                if fallback_info:
                                    fallback_fontname, fallback_font_obj = fallback_info
                                    # style_key = fallback_fontname.split('-')[-1] # Get style like 'regular', 'bold' -> No longer reliable, name is just Fallback-style
                                    
                                    logger.warning(
                                        # f"Font '{font_name_original}' failed on page {page_num}. Error: {font_error}. Using fallback style '{style_key}'. Text: '{text[:20]}...'" -> Use fallback_fontname
                                         f"Font '{font_name_original}' failed on page {page_num}. Error: {font_error}. Using fallback font '{fallback_fontname}'. Text: '{text[:20]}...'"
                                    )
                                    try:
                                        # Ensure the specific fallback style font is registered
                                        if fallback_font_obj.buffer:
                                            # Register the font using the specific name (e.g., Fallback-bold)
                                            new_page.insert_font(fontname=fallback_fontname, fontbuffer=fallback_font_obj.buffer)
                                        else:
                                             # Use style_key derived correctly inside the try block for error logging
                                             loaded_style_key = fallback_fontname.split('-')[-1]
                                             raise ValueError(f"Fallback font object for {loaded_style_key} has no buffer.")
                                        
                                        # Insert text using the registered fallback font name
                                        new_page.insert_text(
                                            point=origin,
                                            text=text,
                                            fontsize=size,
                                            color=(1, 1, 1),
                                            fontname=fallback_fontname # Use the style-specific fallback name
                                        )
                                    except Exception as fallback_error:
                                        logger.error(
                                            f"Fallback font insertion failed for '{fallback_fontname}' on page {page_num}. Error: {fallback_error}. Skipping text: '{text[:20]}...'"
                                        )
                                else:
                                    # If no fallback font path configured or different error
                                    logger.error(
                                        f"Font '{font_name_original}' failed on page {page_num} and no usable fallback provided/loaded. Error: {font_error}. Skipping text: '{text[:20]}...'"
                                    )
                                    # Optionally re-raise: raise font_error

            # Copy non-text elements (images, etc.)
            # Use get_images(full=True) to get image bounding boxes
            img_list = page.get_images(full=True)
            img_bboxes = [page.get_image_bbox(img_info) for img_info in img_list]

            for i, img_info in enumerate(img_list):
                xref = img_info[0]
                img_bbox = img_bboxes[i]

                # Check if the bounding box is valid
                if not img_bbox or img_bbox.is_empty or img_bbox.is_infinite:
                    logger.warning(f"Skipping image with invalid/empty bbox on page {page_num}: xref={xref}, bbox={img_bbox}")
                    continue

                base_image = doc.extract_image(xref)
                if not base_image:
                    logger.warning(f"Could not extract image with xref={xref} on page {page_num}")
                    continue

                image_bytes = base_image["image"]

                # Insert the image at its original position using its bounding box
                try:
                    new_page.insert_image(
                        rect=img_bbox,
                        stream=image_bytes
                    )
                except ValueError as img_error:
                     logger.warning(f"Skipping image due to insertion error on page {page_num}: xref={xref}, bbox={img_bbox}, error={img_error}")


        # Save the modified PDF
        # Use garbage collection to ensure resources are freed before saving
        new_doc.save(output_pdf_path, garbage=4, deflate=True)
        new_doc.close()
        doc.close()

        logger.info(f"Successfully processed PDF: {input_pdf_path}")
        return None

    except Exception as e:
        # Ensure documents are closed even if error occurs mid-process
        doc_to_close = locals().get('doc')
        new_doc_to_close = locals().get('new_doc')
        try:
            if doc_to_close:
                doc_to_close.close()
        except Exception as close_ex:
            logger.error(f"Error closing input document: {close_ex}")
        try:
            if new_doc_to_close:
                 new_doc_to_close.close()
        except Exception as close_ex:
            logger.error(f"Error closing output document: {close_ex}")

            
        error_msg = f"Error processing PDF: {str(e)}"
        logger.error(error_msg, exc_info=True) # Log full traceback
        return error_msg 
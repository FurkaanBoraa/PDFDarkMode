import fitz  # PyMuPDF
import logging
import os
import platform # <-- Add platform import
import subprocess # <-- Add subprocess import
import sys # <-- Add sys import
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk # Import Pillow for image resizing
from typing import Optional, Dict, Callable
from tkinterdnd2 import DND_FILES, TkinterDnD # Import TkinterDnD
import threading # Added for running conversion in background
import queue # Added for thread communication
from pathlib import Path # <-- Add pathlib import

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global cache for loaded fallback fonts {style_key: fitz.Font}
fallback_fonts: Dict[str, Optional[fitz.Font]] = {}

# Dictionary to hold paths to fallback fonts
fallback_paths = {}

# --- Helper function for PyInstaller assets ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Helper function to draw rounded rectangles on a canvas
def create_rounded_rect(canvas, x1, y1, x2, y2, radius, outline_color, outline_width, fill_color):
    """Draws a rounded rectangle on a tkinter canvas."""
    points = [
        x1 + radius, y1,
        x1 + radius, y1,
        x2 - radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1 + radius,
        x1, y1,
    ]
    # Use empty string for fill if you only want outline
    actual_fill = fill_color if fill_color else ""
    return canvas.create_polygon(points, fill=actual_fill, outline=outline_color, width=outline_width, smooth=True)

def load_fallback_font(style='regular') -> Optional[fitz.Font]:
    """Loads a fallback font based on style, using caching."""
    global fallback_fonts, fallback_paths
    if style in fallback_fonts:
        return fallback_fonts[style]

    font_path = fallback_paths.get(style)
    if not font_path or not os.path.exists(font_path):
        logger.error(f"Fallback font path not found or invalid for style '{style}': {font_path}")
        return None

    try:
        font = fitz.Font(fontfile=font_path)
        fallback_fonts[style] = font
        logger.info(f"Successfully loaded fallback font '{style}' from {font_path}")
        return font
    except Exception as e:
        logger.error(f"Failed to load fallback font '{style}' from {font_path}: {e}", exc_info=True)
        fallback_fonts[style] = None # Cache failure to prevent retries
        return None

def get_fallback_font_for_span(fontname: str, flags: int) -> Optional[tuple[fitz.Font, str]]:
    """Determines the best fallback font style based on flags and attempts to load it."""
    # Correctly check flags using bitwise AND
    is_italic = bool(flags & 1)  # Check for Italic flag
    is_bold = bool(flags & 16) # Check for Bold flag
    logger.debug(f"Attempting fallback for font '{fontname}' (Flags: {flags}, Bold: {is_bold}, Italic: {is_italic})")

    style_priority = []
    if is_bold and is_italic:
        style_priority = ['bold_italic', 'bold', 'italic', 'regular']
    elif is_bold:
        style_priority = ['bold', 'regular']
    elif is_italic:
        style_priority = ['italic', 'regular']
    else:
        style_priority = ['regular']

    for style_key in style_priority:
        logger.debug(f"Trying style: '{style_key}'")
        font = load_fallback_font(style_key)
        if font:
            fallback_fontname = f"Fallback-{style_key}"
            logger.debug(f"SUCCESS: Found fallback font '{fallback_fontname}' for '{fontname}' (Style: {style_key})")
            return font, fallback_fontname

    logger.warning(f"FAILURE: No suitable fallback font found for '{fontname}' after trying styles: {style_priority}")
    return None, None

def convert_pdf_colors(input_pdf_path: str, output_pdf_path: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> Optional[str]:
    """Converts PDF text to white and background to black, with progress callback."""
    global fallback_fonts, fallback_paths # Ensure access to globals

    # Clear font cache at the beginning of each conversion
    fallback_fonts.clear()
    logger.info("Fallback font cache cleared.")

    # Basic validation
    if not isinstance(input_pdf_path, str) or not input_pdf_path.lower().endswith('.pdf'):
        return "Invalid input file path. Must be a string ending with .pdf"
    if not isinstance(output_pdf_path, str) or not output_pdf_path.lower().endswith('.pdf'):
        return "Invalid output file path. Must be a string ending with .pdf"

    try:
        doc = fitz.open(input_pdf_path)
        new_doc = fitz.open() # Create a new PDF for output

        total_pages = len(doc)
        logger.info(f"Starting PDF conversion for '{input_pdf_path}' ({total_pages} pages)")

        # Define colors
        white = (1, 1, 1)
        black = (0, 0, 0)

        for page_num, page in enumerate(doc):
            logger.info(f"Processing page {page_num + 1}/{total_pages}")

            # Create a new page in the output document with the same dimensions
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)

            # Set background to black
            # Use Shape to draw rect to avoid opacity issues sometimes seen with draw_rect
            bg_shape = new_page.new_shape()
            bg_shape.draw_rect(new_page.rect)
            bg_shape.finish(color=black, fill=black, width=0) # Fill with black
            bg_shape.commit()

            # Extract drawings first and draw them in white
            drawings = page.get_drawings()
            drawing_shape = new_page.new_shape()
            logger.debug(f"Page {page_num + 1}: Found {len(drawings)} drawing paths.")
            for path in drawings:
                # Make lines/borders white, keep fill transparent unless it's explicitly black
                path_color = white # Default to white lines
                fill_color = path['fill'] # Use original fill color
                path_width = path['width'] if path['width'] is not None else 1.0 # Default width if None

                # Process different path types
                for item in path["items"]:
                    op = item[0]
                    if op == "l": # line
                        drawing_shape.draw_line(item[1], item[2])
                    elif op == "re": # rectangle
                        # If rectangle is filled (likely a background or table cell), make fill white too
                        if path['fill']:
                           fill_color = white
                        drawing_shape.draw_rect(item[1])
                    elif op == "c": # curve
                         drawing_shape.draw_bezier(item[1], item[2], item[3], item[4])
                    elif op == "qu": # quad
                         drawing_shape.draw_quad(item[1])
                    # Finalize and commit each path segment individually or group logically
                # Finish the path segment
                drawing_shape.finish(color=path_color, fill=fill_color, width=path_width, even_odd=path.get('even_odd', False))
            drawing_shape.commit() # Commit all drawing paths for the page
            logger.debug(f"Page {page_num + 1}: Finished processing drawings.")

            # Extract text blocks and insert with white color and fallback fonts
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] == 0: # Text block
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"]
                            fontname = span["font"]
                            fontsize = span["size"]
                            origin = fitz.Point(span["origin"][0], span["origin"][1])
                            flags = span["flags"]

                            # Attempt to find the font in the original document or load system font
                            try:
                                font = fitz.Font(fontname=fontname)
                                # Check if font contains necessary glyphs (simple check)
                                if not all(font.has_glyph(ord(c)) for c in text if ord(c) > 31):
                                    raise ValueError("Missing glyphs")
                                current_fontname = fontname
                                current_font = font
                            except Exception as e:
                                # Font not found, invalid, or missing glyphs - use fallback
                                logger.warning(f"Font '{fontname}' failed on page {page_num + 1} (Size: {fontsize:.2f}, Flags: {flags}): {e}. Text: '{text[:30]}...' Attempting fallback.")
                                fallback_font, fallback_fontname = get_fallback_font_for_span(fontname, flags)
                                if fallback_font:
                                    current_font = fallback_font
                                    current_fontname = fallback_fontname
                                    logger.info(f"Using fallback '{current_fontname}' for font '{fontname}'.")
                                else:
                                    logger.error(f"Critical: No fallback font available for '{fontname}'. Skipping text: '{text[:30]}...'" )
                                    continue # Skip this span if no fallback available

                            # Insert text with the determined font and white color
                            try:
                                insert_rc = new_page.insert_font(fontname=current_fontname, fontbuffer=current_font.buffer)
                                if insert_rc < 0:
                                     logger.error(f"Failed to insert font {current_fontname} into new page {page_num + 1}. RC: {insert_rc}")
                                     continue # Skip if font insertion failed

                                new_page.insert_text(origin, text, fontname=current_fontname,
                                                     fontsize=fontsize, color=white)
                            except Exception as text_insert_error:
                                 logger.error(f"Error inserting text with font {current_fontname} on page {page_num + 1}: {text_insert_error}. Text: '{text[:30]}...'", exc_info=True)

            # Handle Images (Copy images from original page to new page)
            img_list = page.get_images(full=True)
            if img_list:
                 logger.info(f"Page {page_num + 1}: Found {len(img_list)} images.")
                 for img_info in img_list:
                      xref = img_info[0]
                      base_image = doc.extract_image(xref)
                      img_bytes = base_image["image"]
                      img_rect = page.get_image_rects(xref)[0] # Get the first rectangle for the image
                      try:
                          new_page.insert_image(img_rect, stream=img_bytes)
                          logger.debug(f"Page {page_num + 1}: Inserted image with xref {xref} at {img_rect}")
                      except Exception as img_err:
                           logger.error(f"Page {page_num + 1}: Failed to insert image xref {xref}: {img_err}", exc_info=True)

            # --- Call progress callback --- 
            if progress_callback:
                try:
                    progress_callback(page_num + 1, total_pages)
                except Exception as cb_err:
                     logger.warning(f"Progress callback failed on page {page_num + 1}: {cb_err}", exc_info=False) # Don't log full trace for callback errors

        # Save the new document
        new_doc.save(output_pdf_path, garbage=4, deflate=True, clean=True)
        new_doc.close()
        doc.close()
        logger.info(f"Successfully created dark mode PDF: '{output_pdf_path}'")
        return None # Indicate success

    except FileNotFoundError:
        error_msg = f"Error: Input file not found at '{input_pdf_path}'"
        logger.error(error_msg)
        return error_msg
    except fitz.fitz.FileDataError as e:
        error_msg = f"Error: Corrupt or invalid PDF file '{input_pdf_path}'. Details: {e}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred during PDF processing: {e}"
        logger.error(error_msg, exc_info=True) # Log full traceback
        return error_msg

class PDFDarkModeApp:
    def __init__(self, root):
        self.root = root # root is now a TkinterDnD.Tk object
        self.root.title("PDF Dark Mode Converter")
        self.root.configure(bg="black", padx=50, pady=50)

        # Center the window shortly after it's drawn
        self.root.after(10, self.center_window)

        self.input_pdf_path = None
        self.output_pdf_path = None
        self.button_state = tk.NORMAL
        self.preview_image_tk = None
        self.upload_icon_image = None
        self.output_preview_image_tk = None
        self.progress_fill_id = None # ID for the progress bar fill rectangle
        self.app_state = "initial" # Add state variable: initial, ready, converting, finished

        # --- Threading & Queue --- 
        self.conversion_thread = None
        self.progress_queue = queue.Queue()
        self.status_animation_after_id = None # To store the .after() id

        # --- Styling ---
        self.style = ttk.Style()
        self.style.configure("TLabel", background="black", foreground="white", font=("Inter", 22, "bold"))
        self.style.configure("TFrame", background="black")
        self.style.configure("Clickable.TLabel", background="black", foreground="white", font=("Inter", 22, "bold", "italic"))
        self.style.configure("Status.TLabel", background="black", foreground="white", font=("Inter", 22, "bold")) # Default style

        # --- Component 1: Status Label ---
        self.status_label = ttk.Label(root, text="Okunabilir hale getirmek istediğin dosyayı seç veya alana sürükle", style="Status.TLabel", wraplength=root.winfo_screenwidth() - 100)
        self.status_label.pack(pady=(0, 40))

        # --- Component 2: Boxes and Arrow ---
        self.component2_frame = ttk.Frame(root, style="TFrame")
        self.component2_frame.pack(pady=(0, 40))

        box_width = 371
        box_height = 466
        corner_radius = 10
        border_width = 6
        border_color = "white"
        fill_color = "black"
        arrow_gap = 35

        # Load arrow image early to get width for progress bar calculation
        arrow_width = 0
        try:
            # Use Pillow to reliably get size without creating Tk object yet
            arrow_img_path = resource_path("arrow.png") # <-- Use resource_path
            arrow_img_pil = Image.open(arrow_img_path)
            arrow_width = arrow_img_pil.width
            self.arrow_image = ImageTk.PhotoImage(arrow_img_pil) # Store Tk image for later use
            logger.debug(f"Arrow image loaded from {arrow_img_path}, width: {arrow_width}")
        except Exception as e:
             logger.warning(f"Could not load arrow.png to determine width: {e}")
             # Estimate or use a default if needed, or make progress bar width fixed
             arrow_width = 50 # Estimate if loading failed

        # Left Box
        self.left_box = tk.Canvas(self.component2_frame, width=box_width, height=box_height, bg=fill_color, highlightthickness=0)
        self.left_box.pack(side=tk.LEFT, padx=(0, arrow_gap))

        # Arrow Label
        if hasattr(self, 'arrow_image'):
            self.arrow_label = tk.Label(self.component2_frame, image=self.arrow_image, background=fill_color)
            self.arrow_label.image = self.arrow_image # Keep reference
            self.arrow_label.pack(side=tk.LEFT, padx=(0, arrow_gap))
        else:
            self.arrow_placeholder = tk.Label(self.component2_frame, text="->", font=("Inter", 40, "bold"), background=fill_color, foreground=border_color)
            self.arrow_placeholder.pack(side=tk.LEFT, padx=(0, arrow_gap))

        # Right Box
        self.right_box = tk.Canvas(self.component2_frame, width=box_width, height=box_height, bg=fill_color, highlightthickness=0)
        self.right_box.pack(side=tk.LEFT)
        create_rounded_rect(self.right_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, border_color, border_width, "")

        # --- Component 3: Convert Button / Progress Bar Container ---
        self.button_progress_frame = ttk.Frame(root, style="TFrame")
        self.button_progress_frame.pack()

        button_height = 40 # Progress bar height will match this
        # Calculate dynamic progress bar width
        self.progress_bar_width = box_width + arrow_gap + arrow_width + arrow_gap + box_width
        logger.debug(f"Calculated progress bar width: {self.progress_bar_width}")

        # --- Create Button Canvas (initially shown) ---
        button_width_fixed = 256 # Keep button fixed size
        button_fill = "#585858"
        self.convert_button_canvas = tk.Canvas(self.button_progress_frame, width=button_width_fixed, height=button_height, bg=button_fill, highlightthickness=0)
        self.button_border_id = create_rounded_rect(self.convert_button_canvas, border_width/2, border_width/2, button_width_fixed - border_width/2, button_height - border_width/2, corner_radius, border_color, border_width, "")
        self.button_text_id = self.convert_button_canvas.create_text(button_width_fixed/2, button_height/2, text="DÖNÜŞTÜR", fill=border_color, font=("Inter", 16, "bold"))
        self.convert_button_canvas.bind("<Button-1>", self.start_conversion_event)
        self.convert_button_canvas.pack() # Show button initially

        # --- Create Custom Progress Bar Canvas (initially hidden) ---
        self.progress_canvas = tk.Canvas(self.button_progress_frame, width=self.progress_bar_width, height=button_height, bg=fill_color, highlightthickness=0)
        # Draw initial border but don't pack yet
        create_rounded_rect(self.progress_canvas, border_width/2, border_width/2, self.progress_bar_width - border_width/2, button_height - border_width/2, corner_radius, border_color, border_width, "")

        # --- Setup Drop Target for the ROOT window ---
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.handle_drop)
        logger.debug("Root window registered as drop target and <<Drop>> event bound.")
        # Removed drop target setup from self.left_box

        # Initial setup of icon/text in left box
        self.recreate_left_box_initial_content() # This now also draws initial border

    def center_window(self):
        """Centers the window on the screen."""
        self.root.update_idletasks() # Ensure window dimensions are up-to-date
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def handle_drop(self, event):
        """Handles file drop events on the left box."""
        filepath_string = event.data
        logger.debug(f"<<Drop>> event received. Data: '{filepath_string}'")

        # Clean up the path string (remove braces, handle potential quoting)
        if filepath_string.startswith('{') and filepath_string.endswith('}'):
            # Take content between braces, handle cases where path itself has spaces
            # This might need more robust parsing if paths have braces
             filepath = filepath_string[1:-1]
             # Further check if path was quoted inside braces
             if filepath.startswith('"') and filepath.endswith('"'):
                  filepath = filepath[1:-1]
        else:
            filepath = filepath_string

        # Check if the cleaned path exists and is a PDF file
        if filepath and os.path.isfile(filepath) and filepath.lower().endswith('.pdf'):
            logger.info(f"File dropped: {filepath}")
            self.process_selected_file(filepath)
        else:
            logger.warning(f"Dropped item is not a valid PDF file path: '{filepath}'")
            messagebox.showwarning("Invalid Drop", "Lütfen yalnızca tek bir PDF dosyası sürükleyin.")


    def select_file_event(self, event=None):
        """Wrapper for file dialog selection."""
        logger.debug("Entering select_file_event (click).")
        filepath = filedialog.askopenfilename(
            title="Select Input PDF",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*.*"))
        )
        if filepath:
            logger.info(f"File selected via dialog: {filepath}")
            self.process_selected_file(filepath)
        else:
            logger.info("File selection cancelled.")


    def process_selected_file(self, filepath: str):
        """Processes the selected/dropped PDF: Generates preview and updates UI."""
        logger.debug(f"Processing file: {filepath}")
        doc = None
        try:
            # Define dimensions
            box_width = 371
            box_height = 466
            border_width = 6
            corner_radius = 10
            logger.debug(f"Processing with Box dimensions: width={box_width}, height={box_height}, border={border_width}")

            # --- Update state --- 
            self.input_pdf_path = filepath
            base_name = os.path.basename(filepath)
            # Reset status label to non-clickable state before showing standard message
            self.status_label.config(text="DÖNÜŞTÜR butonuna bas", style="Status.TLabel", cursor="")
            self.status_label.unbind("<Button-1>")
            self.app_state = "ready" # Set state to ready for conversion
            logger.info(f"Input PDF set: {self.input_pdf_path}, App state: {self.app_state}")

            # --- Clear existing content --- 
            logger.debug("Clearing left and right boxes for preview.")
            self.left_box.delete("all") 
            self.right_box.configure(bg="black") # Ensure right box is black before clearing
            self.right_box.delete("all") 
            self.right_box.config(cursor="") # Reset cursor
            self.right_box.unbind("<Button-1>") # Unbind click

            # --- Render and Resize PDF Preview using Pillow --- 
            logger.debug("Opening PDF document for preview.")
            doc = fitz.open(self.input_pdf_path)
            if len(doc) == 0: raise ValueError("PDF document has no pages.")
            page = doc[0]
            logger.debug(f"Processing page 0: {page.rect}")

            target_width_available = box_width - (2 * border_width)
            target_height_available = box_height - (2 * border_width)
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            logger.debug(f"Available space: width={target_width_available}, height={target_height_available}")
            logger.debug(f"Original page size: width={page_width}, height={page_height}")

            if page_width <= 0 or page_height <= 0:
                raise ValueError(f"Invalid page dimensions: {page_width}x{page_height}")

            # Calculate zoom factor to fit within available space
            zoom_w = target_width_available / page_width
            zoom_h = target_height_available / page_height
            zoom = min(zoom_w, zoom_h)
            logger.debug(f"Calculated zoom factors: width_zoom={zoom_w:.4f}, height_zoom={zoom_h:.4f}, chosen_zoom={zoom:.4f}")

            # Calculate final target dimensions for the preview image
            final_width = int(page_width * zoom)
            final_height = int(page_height * zoom)
            logger.debug(f"Target preview dimensions: width={final_width}, height={final_height}")

            # Render pixmap at a reasonable base resolution
            mat = fitz.Matrix(1, 1) # Render at original scale
            logger.debug("Rendering pixmap at native scale (dpi=150).")
            pix = page.get_pixmap(matrix=mat, dpi=150)
            logger.debug(f"Pixmap rendered: width={pix.width}, height={pix.height}, alpha={pix.alpha}")

            # Close PDF document now that we have the pixmap
            if doc: doc.close(); doc = None
            logger.debug("PDF document closed.")

            # --- Convert pixmap to Pillow Image and Resize --- 
            logger.debug("Converting pixmap to Pillow Image.")
            if pix.alpha:
                pil_image = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
            else:
                pil_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            logger.debug(f"Pillow Image created: size={pil_image.size}")

            logger.debug(f"Resizing Pillow Image to {final_width}x{final_height} using LANCZOS.")
            resized_pil_image = pil_image.resize((final_width, final_height), Image.Resampling.LANCZOS)
            logger.debug(f"Pillow Image resized: size={resized_pil_image.size}")

            # --- Convert resized Pillow Image to Tkinter PhotoImage --- 
            logger.debug("Converting resized Pillow Image to tk.PhotoImage.")
            self.preview_image_tk = ImageTk.PhotoImage(resized_pil_image)
            logger.debug(f"PhotoImage created from resized Pillow image: {self.preview_image_tk}")
            tk_img_width = self.preview_image_tk.width()
            tk_img_height = self.preview_image_tk.height()
            logger.debug(f"PhotoImage dimensions (Tkinter): width={tk_img_width}, height={tk_img_height}")

            # --- Display Preview --- 
            logger.debug("Displaying preview image.")
            create_rounded_rect(self.left_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, "white", border_width, "")
            img_x_pos = box_width / 2
            img_y_pos = box_height / 2
            logger.debug(f"Placing PhotoImage on canvas at ({img_x_pos}, {img_y_pos}) with anchor=CENTER.")
            self.left_box.create_image(img_x_pos, img_y_pos, anchor=tk.CENTER, image=self.preview_image_tk)
            logger.debug("create_image called.")
            # Reset cursor for left box now that preview is shown
            self.left_box.config(cursor="")
            self.left_box.unbind("<Enter>") # Unbind hover effects
            self.left_box.unbind("<Leave>")

            # --- Redraw Right Box & Enable Button --- 
            logger.debug("Redrawing right box border (black background) and enabling button after preview.")
            # Ensure right box is not clickable yet
            self.right_box.config(cursor="")
            self.right_box.unbind("<Button-1>")
            create_rounded_rect(self.right_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, "white", border_width, "")
            self.set_button_state(tk.NORMAL)
            logger.debug(f"Processing finished for file: {filepath}")

        except Exception as e:
             if doc: doc.close() # Ensure doc is closed on error
             error_msg = f"Error processing selected/dropped file: {e}"
             logger.error(error_msg, exc_info=True)
             messagebox.showerror("PDF Processing Error", error_msg)
             # Reset state
             logger.debug("Resetting state after error during file processing.")
             self.input_pdf_path = None
             self.status_label.config(text="Okunabilir hale getirmek istediğin dosyayı seç veya alana sürükle", style="Status.TLabel", cursor="")
             self.status_label.unbind("<Button-1>")
             # Reset boxes to initial state
             self.recreate_left_box_initial_content() # Handles left box clearing/redrawing
             self.right_box.configure(bg="black") # Ensure right box is black on error reset
             self.right_box.delete("all") # Clear right box
             # Redraw right border
             box_width = 371
             box_height = 466
             border_width = 6
             corner_radius = 10
             create_rounded_rect(self.right_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, "white", border_width, "")
             self.set_button_state(tk.NORMAL)
             self.app_state = "initial" # Reset state on error
             # Ensure cursor is reset on error too if recreate doesn't handle it
             self.left_box.config(cursor="")

    def recreate_left_box_initial_content(self):
        """Helper to redraw the initial icon and text in the left box."""
        logger.debug("Recreating initial content in left box.")
        # Define needed variables locally or ensure they are accessible
        box_width = 371
        box_height = 466
        fill_color = "black"
        border_color = "white"
        border_width = 6
        corner_radius = 10

        # Clear and Re-draw border
        self.left_box.delete("all")
        create_rounded_rect(self.left_box, border_width/2, border_width/2,
                            box_width - border_width/2, box_height - border_width/2,
                            corner_radius, border_color, border_width, "")

        # Re-create Icon Widget
        try:
            # Reload image if necessary or use cached
            if not self.upload_icon_image:
                 logger.debug("Reloading upload icon image.")
                 icon_path = resource_path("add_file.png") # <-- Use resource_path
                 self.upload_icon_image = tk.PhotoImage(file=icon_path)

            self.upload_icon_widget = tk.Label(self.left_box, image=self.upload_icon_image, background=fill_color)
            self.upload_icon_widget.image = self.upload_icon_image
        except tk.TclError:
             logger.warning("Could not load add_file.png on reset.")
             self.upload_icon_widget = tk.Label(self.left_box, text="[Icon Err]", background=fill_color, foreground=border_color, font=("Inter", 16, "bold"))

        # Re-create Text Widget
        self.upload_text_widget = tk.Label(self.left_box, text="Sürükle veya tıklayıp seç", background=fill_color, foreground=border_color, font=("Inter", 16, "bold"))

        # Re-place elements onto the canvas
        icon_y_pos = box_height / 2 - 50
        text_y_pos = icon_y_pos + 100
        self.left_box.create_window(box_width / 2, icon_y_pos, window=self.upload_icon_widget)
        self.left_box.create_window(box_width / 2, text_y_pos, window=self.upload_text_widget)

        # Bind clicks to widgets for file selection
        logger.debug("Re-binding click events for initial left box content.")
        self.upload_icon_widget.bind("<Button-1>", self.select_file_event)
        self.upload_text_widget.bind("<Button-1>", self.select_file_event)

        # Bind hover events to the CANVAS for cursor change
        logger.debug("Binding <Enter>/<Leave> to left_box canvas for cursor.")
        self.left_box.bind("<Enter>", self.on_left_box_enter)
        self.left_box.bind("<Leave>", self.on_left_box_leave)
        # Set initial cursor (optional, good practice)
        self.left_box.config(cursor="")

    def on_left_box_enter(self, event):
        """Change cursor to hand when mouse enters the left box (initial state)."""
        # Only change cursor if the app is in the initial state (or ready before conversion)
        # Or simply check if the specific widgets exist? Less state dependent.
        if hasattr(self, 'upload_icon_widget') and self.upload_icon_widget.winfo_exists():
             self.left_box.config(cursor="hand2")

    def on_left_box_leave(self, event):
        """Change cursor back to default when mouse leaves the left box."""
        self.left_box.config(cursor="")

    def set_button_state(self, state):
        """Visually enable/disable the canvas button."""
        self.button_state = state
        # Keep border white when enabled, grey when disabled
        new_border_color = "white" if state == tk.NORMAL else "#555555"
        # Text color matches border state
        new_text_color = "white" if state == tk.NORMAL else "#555555"

        # Background of the canvas itself doesn't change, only border/text
        if hasattr(self, 'button_border_id'): # Ensure items exist
             self.convert_button_canvas.itemconfig(self.button_border_id, outline=new_border_color)
        if hasattr(self, 'button_text_id'):
             self.convert_button_canvas.itemconfig(self.button_text_id, fill=new_text_color)

    def animate_status_dots(self, dot_count=0):
        """Animates the dots for the 'Converting...' status message."""
        if self.status_animation_after_id is None:
             # Animation was cancelled/stopped
             return
        base_text = "Dönüştürülüyor"
        dots = "." * (dot_count % 4)
        self.status_label.config(text=f"{base_text}{dots}")
        # Schedule next update
        self.status_animation_after_id = self.root.after(500, self.animate_status_dots, dot_count + 1)

    def stop_status_animation(self):
        """Stops the status label dot animation."""
        if self.status_animation_after_id:
            self.root.after_cancel(self.status_animation_after_id)
            self.status_animation_after_id = None
            logger.debug("Status animation stopped.")

    def update_progress(self, current_page, total_pages):
        """Callback function to update progress bar from conversion thread."""
        # Put progress data into the queue for the main thread to process
        self.progress_queue.put((current_page, total_pages))

    def check_progress_queue(self):
        """Checks the queue for progress updates and handles completion."""
        try:
            while True: # Process all pending messages
                message = self.progress_queue.get_nowait()
                if isinstance(message, tuple) and len(message) == 2:
                    if message[0] == "DONE":
                        # Conversion finished message
                        logger.debug("Received DONE signal from worker thread.")
                        result = message[1]
                        self.handle_conversion_complete(result)
                        self.conversion_thread = None # Clear thread reference
                        return # Stop checking queue
                    else:
                        # --- Progress update message --- 
                        current_page, total_pages = message
                        progress_value = (current_page / total_pages) * 100
                        logger.debug(f"Progress update received: {current_page}/{total_pages} ({progress_value:.1f}%)")

                        # --- Update Custom Progress Bar Canvas --- 
                        border_width = 6 # Make consistent
                        corner_radius = 10
                        progress_bar_height = 40
                        fill_color = "white"

                        # Calculate width of the fill area inside the border
                        fill_area_width = self.progress_bar_width - border_width
                        fill_rect_width = (progress_value / 100) * fill_area_width

                        # Define coordinates for the fill rectangle
                        x1 = border_width / 2
                        y1 = border_width / 2
                        x2 = x1 + fill_rect_width
                        y2 = progress_bar_height - border_width / 2

                        # Delete previous fill rectangle if it exists
                        if self.progress_fill_id:
                            self.progress_canvas.delete(self.progress_fill_id)

                        # Draw the new fill rectangle (ensure x2 >= x1)
                        if x2 > x1:
                             # Use create_rounded_rect for fill for consistency
                             self.progress_fill_id = create_rounded_rect(self.progress_canvas, x1, y1, x2, y2,
                                                                           corner_radius, fill_color, 0, fill_color) # No border for fill, just fill
                             # Raise the border item so it's drawn on top (assuming border is item ID 1, usually)
                             # A safer way might be to store border ID, but this often works
                             self.progress_canvas.tag_raise(1) # Attempt to raise the first item (border)
                        else:
                             self.progress_fill_id = None # No fill if width is zero

                        self.root.update_idletasks() # Update UI immediately
                else:
                    logger.warning(f"Received unexpected message in queue: {message}")

        except queue.Empty:
            pass # No messages currently in queue

        # If conversion thread is still referenced (meaning DONE not received yet), schedule next check
        if self.conversion_thread:
            self.root.after(100, self.check_progress_queue)

    def start_conversion_event(self, event):
         """Wrapper for start_conversion or reset based on state."""
         logger.debug(f"Button clicked. Current state: {self.app_state}")
         if self.app_state == "finished":
             logger.info("Resetting application state.")
             self.reset_application()
         elif self.app_state == "ready" and self.button_state == tk.NORMAL:
             logger.info("Starting conversion.")
             self.start_conversion()
         else:
             logger.warning(f"Button click ignored. State: {self.app_state}, Button State: {self.button_state}")

    def conversion_worker(self):
        """The actual work done in the conversion thread."""
        result = None
        try:
            self.app_state = "converting" # Set state during conversion
            logger.info(f"Conversion thread started: {self.input_pdf_path} -> {self.output_pdf_path}")
            # Pass the queue-based callback method
            result = convert_pdf_colors(self.input_pdf_path, self.output_pdf_path, self.update_progress)
            logger.info("Conversion thread finished.")
        except Exception as e:
             logger.error(f"Exception in conversion worker thread: {e}", exc_info=True)
             result = f"Thread Error: {e}" # Ensure result indicates error
        finally:
             # Put final result/status into the queue for main thread
             self.progress_queue.put(("DONE", result))

    def start_conversion(self):
        """Initiates the PDF conversion process in a background thread."""
        if not self.input_pdf_path:
            messagebox.showwarning("No File Selected", "Lütfen önce dönüştürülecek bir PDF dosyası seçin.")
            return

        logger.debug("Start conversion process initiated.")

        # Generate output path
        output_dir = os.path.dirname(self.input_pdf_path)
        base_name = os.path.basename(self.input_pdf_path)
        output_filename = f"output_{base_name}"
        self.output_pdf_path = os.path.join(output_dir, output_filename)
        logger.info(f"Output path set to: {self.output_pdf_path}")

        # --- Update UI for Conversion Start ---
        logger.debug("Switching button to progress canvas.")
        self.convert_button_canvas.pack_forget()
        # Clear previous fill if any
        if self.progress_fill_id:
            self.progress_canvas.delete(self.progress_fill_id)
            self.progress_fill_id = None
        # Ensure border is drawn (might be overkill but safe)
        border_width = 6
        corner_radius = 10
        create_rounded_rect(self.progress_canvas, border_width/2, border_width/2, self.progress_bar_width - border_width/2, 40 - border_width/2, corner_radius, "white", border_width, "")
        self.progress_canvas.pack() # Show progress canvas
        self.set_button_state(tk.DISABLED)

        # Start status animation
        self.stop_status_animation() # Ensure any previous animation is stopped
        self.status_label.config(text="Dönüştürülüyor") # Initial text before dots
        self.status_animation_after_id = self.root.after(500, self.animate_status_dots) # Start animation
        logger.debug("UI updated for conversion start.")

        self.root.update_idletasks() # Force UI update

        # --- Start Conversion Thread ---
        logger.info(f"Starting conversion worker thread for: {self.input_pdf_path}")
        self.conversion_thread = threading.Thread(target=self.conversion_worker, daemon=True)
        self.conversion_thread.start()

        # --- Start checking the progress queue --- 
        self.root.after(100, self.check_progress_queue)

    def handle_conversion_complete(self, result):
        """Handles UI updates after conversion thread finishes."""
        logger.info(f"Handling conversion completion. Result: {result}")
        # --- Final UI Updates ---
        self.stop_status_animation()

        # Hide progress canvas, show button again
        logger.debug("Switching progress canvas back to button.")
        self.progress_canvas.pack_forget()
        self.convert_button_canvas.pack()
        self.set_button_state(tk.NORMAL) # Re-enable button

        if result is None:
            # Success
            try:
                # Create a shorter path for display
                full_path = Path(self.output_pdf_path)
                parts = full_path.parts
                if len(parts) > 3:
                    # Show ellipsis, last two folders, and filename
                    short_path_display = os.path.join("...", parts[-3], parts[-2], parts[-1])
                else:
                    # Show full path if it's already short
                    short_path_display = str(full_path)
                success_msg = f"Dönüştürme başarılı! | {short_path_display}"
                logger.info(f"Displaying short path: {short_path_display} (Full: {self.output_pdf_path})")
            except Exception as path_err:
                # Fallback to full path if shortening fails
                logger.error(f"Error shortening path: {path_err}", exc_info=True)
                success_msg = f"Dönüştürme başarılı! | {self.output_pdf_path}"

            # Configure label for clickable appearance and bind event (to open folder)
            self.status_label.config(text=success_msg, style="Clickable.TLabel", cursor="hand2")
            self.status_label.bind("<Button-1>", self.open_output_location)
            self.app_state = "finished"
            self.set_button_state(tk.NORMAL) # Ensure button is visually enabled
            logger.info(f"Conversion successful: {self.output_pdf_path}, App state: {self.app_state}")
            
            # Show output preview in right box
            self.show_output_preview()

            # Make right box clickable to open the PDF
            logger.debug("Binding click event to right_box to open output PDF.")
            self.right_box.config(cursor="hand2")
            self.right_box.bind("<Button-1>", self.open_output_pdf)
        else:
            # Failure
            error_msg = f"Hata oluştu: {result}"
            # Ensure label is reset to non-clickable on failure
            self.status_label.config(text=error_msg, style="Status.TLabel", cursor="")
            self.status_label.unbind("<Button-1>")
            messagebox.showerror("Conversion Error", f"PDF dönüştürme sırasında bir hata oluştu:\\n\\n{result}")
            # Reset state to allow trying again or selecting new file
            self.app_state = "ready" if self.input_pdf_path else "initial"
            self.set_button_state(tk.NORMAL) # Re-enable button
            # Set button text back to default on error
            self.convert_button_canvas.itemconfig(self.button_text_id, text="DÖNÜŞTÜR")
            logger.error(f"Conversion failed: {result}, App state reset to: {self.app_state}")
            # Reset input state? Optional
            # self.input_pdf_path = None
            # self.recreate_left_box_initial_content()

    def show_output_preview(self):
        """Renders and displays the first page of the OUTPUT PDF in the right box."""
        logger.debug(f"Attempting to show preview of output file: {self.output_pdf_path}")
        if not self.output_pdf_path or not os.path.exists(self.output_pdf_path):
             logger.error(f"Output file path not valid or file doesn't exist: {self.output_pdf_path}")
             self.right_box.delete("all")
             create_rounded_rect(self.right_box, 6/2, 6/2, 371 - 6/2, 466 - 6/2, 10, "white", 6, "") # Redraw border
             self.right_box.create_text(371/2, 466/2, text="Önizleme Yok", fill="#555555", font=("Inter", 18, "bold"))
             return

        doc = None
        try:
            box_width = 371
            box_height = 466
            border_width = 6
            corner_radius = 10
            logger.debug("Opening OUTPUT PDF document for preview.")
            doc = fitz.open(self.output_pdf_path)
            if len(doc) == 0: raise ValueError("Output PDF document has no pages.")
            page = doc[0]

            target_width_available = box_width - (2 * border_width)
            target_height_available = box_height - (2 * border_width)
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            if page_width <= 0 or page_height <= 0:
                 raise ValueError(f"Invalid page dimensions in output PDF: {page_width}x{page_height}")

            zoom_w = target_width_available / page_width
            zoom_h = target_height_available / page_height
            zoom = min(zoom_w, zoom_h)
            final_width = int(page_width * zoom)
            final_height = int(page_height * zoom)
            mat = fitz.Matrix(1, 1)
            pix = page.get_pixmap(matrix=mat, dpi=150)
            if doc: doc.close(); doc = None

            if pix.alpha:
                pil_image = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
            else:
                pil_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            resized_pil_image = pil_image.resize((final_width, final_height), Image.Resampling.LANCZOS)
            self.output_preview_image_tk = ImageTk.PhotoImage(resized_pil_image) # Use separate attribute
            logger.debug(f"Output preview PhotoImage created: {self.output_preview_image_tk}")

            # Display in Right Box (with WHITE background)
            logger.debug("Setting right box background to white for output preview.")
            self.right_box.configure(bg="white") # <--- Set background to white HERE
            self.right_box.delete("all")
            create_rounded_rect(self.right_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, "white", border_width, "") # Border is still white
            self.right_box.create_image(box_width / 2, box_height / 2, anchor=tk.CENTER, image=self.output_preview_image_tk)
            logger.debug("Output preview displayed in right box.")

            # Ensure cursor is set correctly based on app state after preview shows
            if self.app_state == "finished":
                self.right_box.config(cursor="hand2")
            else:
                 self.right_box.config(cursor="")

        except Exception as e:
             if doc: doc.close()
             error_msg = f"Error generating output preview: {e}"
             logger.error(error_msg, exc_info=True)
             logger.debug("Setting right box background back to black after preview error.")
             self.right_box.configure(bg="black") # Set back to black on error
             self.right_box.delete("all")
             create_rounded_rect(self.right_box, 6/2, 6/2, 371 - 6/2, 466 - 6/2, 10, "white", 6, "") # Redraw border
             self.right_box.create_text(371/2, 466/2, text="Önizleme Hatası", fill="#FF0000", font=("Inter", 18, "bold"))

    def open_output_pdf(self, event=None):
        """Opens the generated PDF file in the default system viewer."""
        logger.info(f"Attempting to open output PDF: {self.output_pdf_path}")
        if not self.output_pdf_path or not os.path.exists(self.output_pdf_path):
            logger.warning(f"Output path is not set or file does not exist: {self.output_pdf_path}")
            messagebox.showwarning("File Not Found", "Oluşturulan PDF dosyası bulunamadı.")
            return

        filepath = os.path.normpath(self.output_pdf_path) # Normalize path
        system = platform.system()

        try:
            if system == "Windows":
                logger.debug(f"Running command: os.startfile(\"{filepath}\")")
                os.startfile(filepath)
            elif system == "Darwin": # macOS
                logger.debug(f"Running command: open \"{filepath}\"")
                subprocess.run(['open', filepath], check=True)
            else: # Linux and other Unix-like systems
                logger.debug(f"Running command: xdg-open \"{filepath}\"")
                subprocess.run(['xdg-open', filepath], check=True)
            logger.info(f"Successfully initiated opening of {filepath}")
        except FileNotFoundError:
            logger.error(f"Command not found for opening PDF on {system}.")
            messagebox.showerror("Error", f"Varsayılan PDF görüntüleyici açılamadı ({system}).")
        except Exception as e:
            logger.error(f"Failed to open PDF file '{filepath}' on {system}: {e}", exc_info=True)
            messagebox.showerror("Error", f"PDF dosyası açılamadı: {e}")

    def open_output_location(self, event=None):
        """Opens the file explorer to the location of the output PDF."""
        logger.info(f"Attempting to open file location for: {self.output_pdf_path}")
        if not self.output_pdf_path or not os.path.exists(self.output_pdf_path):
            logger.warning(f"Output path is not set or file does not exist: {self.output_pdf_path}")
            messagebox.showwarning("File Not Found", "Oluşturulan PDF dosyası bulunamadı.")
            return

        filepath_raw = self.output_pdf_path
        system = platform.system()
        return_code = None # Variable to store return code

        try:
            if system == "Windows":
                filepath_norm = os.path.normpath(filepath_raw)
                command = ['explorer', '/select,', filepath_norm]
                logger.debug(f"Running command: {' '.join(command)}")
                # Run without check=True, but capture the result
                result = subprocess.run(command)
                return_code = result.returncode
                logger.info(f"'explorer /select' command finished with return code: {return_code}")
                # Don't raise error for common non-zero codes if explorer still worked
                if return_code != 0:
                     logger.warning(f"'explorer /select' returned non-zero exit status {return_code}. This might be okay if the folder opened.")

            elif system == "Darwin": # macOS
                filepath_norm = os.path.normpath(filepath_raw)
                command = ['open', '-R', filepath_norm]
                logger.debug(f"Running command: {' '.join(command)}")
                result = subprocess.run(command, check=True) # Keep check=True for macOS
                return_code = result.returncode
                logger.info(f"'open -R' command finished with return code: {return_code}")

            else: # Linux and other Unix-like systems
                directory = os.path.dirname(os.path.normpath(filepath_raw))
                command = ['xdg-open', directory]
                logger.debug(f"Running command: {' '.join(command)}")
                result = subprocess.run(command, check=True) # Keep check=True for Linux
                return_code = result.returncode
                logger.info(f"'xdg-open' command finished with return code: {return_code}")

        except FileNotFoundError:
             logger.error(f"Command not found for opening file explorer on {system}.")
             messagebox.showerror("Error", f"Dosya gezgini açılamadı ({system}). Komut bulunamadı.")
        except subprocess.CalledProcessError as e: # Catch errors only for non-Windows check=True cases
             logger.error(f"Command failed for {system}: {e}", exc_info=True)
             messagebox.showerror("Error", f"Dosya konumu açılamadı ({system}): {e}")
        except Exception as e:
             # Catch other potential errors like permission issues
             logger.error(f"Failed to open file location '{filepath_raw}' on {system}: {e}", exc_info=True)
             messagebox.showerror("Error", f"Dosya konumu açılırken genel bir hata oluştu: {e}")

    def reset_application(self):
        """Resets the application to its initial state."""
        logger.info("Resetting application UI and state.")
        self.input_pdf_path = None
        self.output_pdf_path = None
        self.app_state = "initial"

        # Reset status label to default non-clickable state
        self.status_label.config(text="Okunabilir hale getirmek istediğin dosyayı seç veya alana sürükle", style="Status.TLabel", cursor="")
        self.status_label.unbind("<Button-1>")

        # Reset left box
        self.recreate_left_box_initial_content()

        # Reset right box (clear preview, set background to black, remove click)
        logger.debug("Resetting right box: setting background to black, clearing content, removing click.")
        self.right_box.configure(bg="black") 
        self.right_box.delete("all")
        self.right_box.config(cursor="") # Reset cursor
        self.right_box.unbind("<Button-1>") # Unbind click
        # Define dimensions needed for border redraw
        box_width = 371
        box_height = 466
        border_width = 6
        corner_radius = 10
        create_rounded_rect(self.right_box, border_width/2, border_width/2, box_width - border_width/2, box_height - border_width/2, corner_radius, "white", border_width, "")

        # Reset button text and state
        self.convert_button_canvas.itemconfig(self.button_text_id, text="DÖNÜŞTÜR")
        self.set_button_state(tk.NORMAL) # Ensure it's visually enabled

        logger.info("Application reset complete.")

# --- Main execution block ---
if __name__ == "__main__":
    # --- Fallback Font Configuration ---
    # Use global fallback_paths defined at the top
    fallback_paths.update({
        'regular': 'C:/Windows/Fonts/arial.ttf',
        'bold': 'C:/Windows/Fonts/arialbd.ttf',
        'italic': 'C:/Windows/Fonts/ariali.ttf',
        'bold_italic': 'C:/Windows/Fonts/arialbi.ttf'
    })

    # --- Logging Configuration ---
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    # Set root logger level potentially lower if needed, but set specific logger to DEBUG
    logging.basicConfig(level=logging.INFO, format=log_format)
    logging.getLogger(__name__).setLevel(logging.DEBUG) # Ensure our logger is set to DEBUG
    # Also set pdf_processor logger if it's used elsewhere and needs debug logs
    logging.getLogger('pdf_processor').setLevel(logging.DEBUG)

    # --- GUI Setup ---
    # Use TkinterDnD.Tk for the root window
    logger.debug("Initializing TkinterDnD root window.")
    main_root = TkinterDnD.Tk() # Use TkinterDnD
    logger.debug("Creating PDFDarkModeApp instance.")
    app = PDFDarkModeApp(main_root)
    logger.debug("Starting mainloop.")
    main_root.mainloop() 
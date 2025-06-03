import streamlit as st
import pandas as pd
import os
import re
import datetime
from io import BytesIO
import tempfile
from PIL import Image as PILImage, ImageDraw, ImageFont
import base64

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph, PageBreak, Image
from reportlab.lib.units import cm, inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# Define sticker dimensions
STICKER_WIDTH = 10 * cm
STICKER_HEIGHT = 15 * cm
STICKER_PAGESIZE = (STICKER_WIDTH, STICKER_HEIGHT)

# Define content box dimensions
CONTENT_BOX_WIDTH = 9.8 * cm
CONTENT_BOX_HEIGHT = 5 * cm

def normalize_column_name(col_name):
    """Normalize column names by removing all non-alphanumeric characters and converting to lowercase"""
    return re.sub(r'[^a-zA-Z0-9]', '', str(col_name)).lower()

def find_column(df, possible_names):
    """Find a column in the DataFrame that matches any of the possible names"""
    normalized_df_columns = {normalize_column_name(col): col for col in df.columns}
    normalized_possible_names = [normalize_column_name(name) for name in possible_names]

    for norm_name in normalized_possible_names:
        if norm_name in normalized_df_columns:
            return normalized_df_columns[norm_name]

    # Check for partial matches
    for norm_name in normalized_possible_names:
        for df_norm_name, original_name in normalized_df_columns.items():
            if norm_name in df_norm_name or df_norm_name in norm_name:
                return original_name

    # Check for line location keywords
    for df_norm_name, original_name in normalized_df_columns.items():
        if ('line' in df_norm_name and 'location' in df_norm_name) or 'lineloc' in df_norm_name:
            return original_name

    return None

def process_uploaded_logo(uploaded_logo, target_width_cm, target_height_cm):
    """Process uploaded logo to fit the specified dimensions"""
    try:
        # Load image from uploaded file
        logo_img = PILImage.open(uploaded_logo)

        # Convert to RGB if necessary
        if logo_img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = PILImage.new('RGB', logo_img.size, (255, 255, 255))
            if logo_img.mode == 'P':
                logo_img = logo_img.convert('RGBA')
            background.paste(logo_img, mask=logo_img.split()[-1] if logo_img.mode in ('RGBA', 'LA') else None)
            logo_img = background

        # Convert cm to pixels for resizing (using 300 DPI)
        dpi = 300
        box_width_px = int(target_width_cm * dpi / 2.54)
        box_height_px = int(target_height_cm * dpi / 2.54)

        # Get original dimensions
        orig_width, orig_height = logo_img.size
        
        # Calculate aspect ratio and resize to fit within bounds while maintaining aspect ratio
        aspect_ratio = orig_width / orig_height
        target_aspect = box_width_px / box_height_px
        
        if aspect_ratio > target_aspect:
            # Image is wider, fit to width
            new_width = box_width_px
            new_height = int(box_width_px / aspect_ratio)
        else:
            # Image is taller, fit to height
            new_height = box_height_px
            new_width = int(box_height_px * aspect_ratio)
        
        # Resize with high quality
        logo_img = logo_img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)

        # Convert to bytes for ReportLab
        img_buffer = BytesIO()
        logo_img.save(img_buffer, format='PNG', quality=100, optimize=False)
        img_buffer.seek(0)

        # Convert back to cm for ReportLab
        final_width_cm = new_width * 2.54 / dpi
        final_height_cm = new_height * 2.54 / dpi

        print(f"LOGO DEBUG: Target: {target_width_cm:.2f}cm x {target_height_cm:.2f}cm")
        print(f"LOGO DEBUG: Final: {final_width_cm:.2f}cm x {final_height_cm:.2f}cm")
        print(f"LOGO DEBUG: Pixels: {new_width}px x {new_height}px")
        
        # Create ReportLab Image with actual dimensions
        return Image(img_buffer, width=final_width_cm*cm, height=final_height_cm*cm)

    except Exception as e:
        st.error(f"Error processing uploaded logo: {e}")
        return None

def generate_qr_code(data_string):
    """Generate a QR code from the given data string"""
    try:
        import qrcode
        from PIL import Image as PILImage

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )

        qr.add_data(data_string)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")

        img_buffer = BytesIO()
        qr_img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        # Increased QR code size to better fit the spanning area
        return Image(img_buffer, width=1.8*cm, height=1.8*cm)
    except Exception as e:
        st.error(f"Error generating QR code: {e}")
        return None

def parse_line_location(location_string):
    """Parse line location string and split into 4 boxes"""
    if not location_string or pd.isna(location_string):
        return ["", "", "", ""]

    parts = str(location_string).split("_")
    result = parts[:4] + [""] * (4 - len(parts))
    return result[:4]

def generate_sticker_labels(df, line_loc_header_width, line_loc_box1_width,
                          line_loc_box2_width, line_loc_box3_width, line_loc_box4_width,
                          uploaded_first_box_logo=None):
    """Generate sticker labels with QR code from DataFrame"""
    try:
        # Define column mappings - Including container/bin type mapping
        column_mappings = {
            'ASSLY': ['assly', 'ASSY NAME', 'Assy Name', 'assy name', 'assyname',
                     'assy_name', 'Assy_name', 'Assembly', 'Assembly Name', 'ASSEMBLY', 'Assembly_Name'],
            'part_no': ['PARTNO', 'PARTNO.', 'Part No', 'Part Number', 'PartNo',
                       'partnumber', 'part no', 'partnum', 'PART', 'part', 'Product Code',
                       'Item Number', 'Item ID', 'Item No', 'item', 'Item'],
            'description': ['DESCRIPTION', 'Description', 'Desc', 'Part Description',
                           'ItemDescription', 'item description', 'Product Description',
                           'Item Description', 'NAME', 'Item Name', 'Product Name'],
            'Part_per_veh': ['QYT', 'QTY / VEH', 'Qty/Veh', 'Qty Bin', 'Quantity per Bin',
                            'qty bin', 'qtybin', 'quantity bin', 'BIN QTY', 'BINQTY',
                            'QTY_BIN', 'QTY_PER_BIN', 'Bin Quantity', 'BIN'],
            'container_type': ['CONTAINER', 'Container', 'container', 'BIN TYPE', 'Bin Type',
                              'bin type', 'bintype', 'BINTYPE', 'Container Type', 'container type',
                              'CONTAINER_TYPE', 'container_type', 'ContainerType'],
            'Type': ['TYPE', 'type', 'Type', 'tyPe', 'Type name'],
            'line_location': ['LINE LOCATION', 'Line Location', 'line location', 'LINELOCATION',
                             'linelocation', 'Line_Location', 'line_location', 'LINE_LOCATION',
                             'LineLocation', 'line_loc', 'lineloc', 'LINELOC', 'Line Loc'],
            'part_status': ['PART STATUS', 'Part Status', 'part status', 'PARTSTATUS',
                           'partstatus', 'Part_Status', 'part_status', 'PART_STATUS',
                           'PartStatus', 'STATUS', 'Status', 'status', 'Item Status',
                           'Component Status', 'Part State', 'State']
        }

        # Find columns
        found_columns = {}
        for key, possible_names in column_mappings.items():
            found_col = find_column(df, possible_names)
            if found_col:
                found_columns[key] = found_col

        # Check required columns
        required_columns = ['ASSLY', 'part_no', 'description']
        missing_required = [col for col in required_columns if col not in found_columns]

        if missing_required:
            st.error(f"Missing required columns: {missing_required}")
            return None, None

        # Create a temporary file for PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            output_pdf_path = tmp_file.name

        # Create PDF with adjusted margins
        def draw_border(canvas, doc):
            canvas.saveState()
            x_offset = (STICKER_WIDTH - CONTENT_BOX_WIDTH) / 2
            y_offset = STICKER_HEIGHT - CONTENT_BOX_HEIGHT - 0.2*cm
            canvas.setStrokeColor(colors.black)
            canvas.setLineWidth(1.5)
            canvas.rect(
                x_offset,
                y_offset,
                CONTENT_BOX_WIDTH,
                CONTENT_BOX_HEIGHT
            )
            canvas.restoreState()

        doc = SimpleDocTemplate(output_pdf_path, pagesize=STICKER_PAGESIZE,
                              topMargin=0.2*cm,
                              bottomMargin=(STICKER_HEIGHT - CONTENT_BOX_HEIGHT - 0.2*cm),
                              leftMargin=(STICKER_WIDTH - CONTENT_BOX_WIDTH) / 2,
                              rightMargin=(STICKER_WIDTH - CONTENT_BOX_WIDTH) / 2)

        # Define styles
        header_style = ParagraphStyle(name='HEADER', fontName='Helvetica-Bold', fontSize=8, alignment=TA_CENTER, leading=9)
        ASSLY_style = ParagraphStyle(
            name='ASSLY',
            fontName='Helvetica',
            fontSize=9,
            alignment=TA_LEFT,
            leading=11,
            spaceAfter=0,
            wordWrap='CJK',
            autoLeading="max"
        )
        Part_style = ParagraphStyle(
            name='PART NO',
            fontName='Helvetica-Bold',
            fontSize=11,
            alignment=TA_LEFT,
            leading=13,
            spaceAfter=0,
            wordWrap='CJK',
            autoLeading="max"
        )
        # Style for part status box
        Part_status_style = ParagraphStyle(
            name='PART STATUS',
            fontName='Helvetica-Bold',
            fontSize=9,
            alignment=TA_CENTER,
            leading=11,
            spaceAfter=0,
            wordWrap='CJK',
            autoLeading="max"
        )
        desc_style = ParagraphStyle(name='PART DESC', fontName='Helvetica', fontSize=7, alignment=TA_LEFT, leading=8, spaceAfter=0, wordWrap='CJK', autoLeading="max")
        partper_style = ParagraphStyle(name='Quantity', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        container_style = ParagraphStyle(name='Container', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        Type_style = ParagraphStyle(name='Quantity', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        date_style = ParagraphStyle(name='DATE', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        location_style = ParagraphStyle(name='Location', fontName='Helvetica', fontSize=8, alignment=TA_CENTER, leading=10)

        content_width = CONTENT_BOX_WIDTH
        all_elements = []
        today_date = datetime.datetime.now().strftime("%d-%m-%Y")

        # Handle uploaded logo for first box
        first_box_logo = None
        if uploaded_first_box_logo is not None:
            # Logo takes 23% of total content width
            logo_width_cm = (content_width * 0.23) / cm  # 23% of content width in cm
            logo_height_cm = 0.75  # 0.75cm height (within 0.85cm row height)

            print(f"LOGO CALCULATION:")
            print(f"Content width: {content_width/cm:.2f}cm")
            print(f"Logo width (23%): {logo_width_cm:.2f}cm")
            print(f"Logo height: {logo_height_cm:.2f}cm")

            first_box_logo = process_uploaded_logo(uploaded_first_box_logo, logo_width_cm, logo_height_cm)
            if first_box_logo:
                st.success(f"✅ Logo processed - Size: {logo_width_cm:.2f}cm x {logo_height_cm:.2f}cm (23% width)")
            else:
                st.error("❌ Failed to process uploaded logo")

        # Process each row
        total_rows = len(df)
        progress_bar = st.progress(0)

        for index, row in df.iterrows():
            progress_bar.progress((index + 1) / total_rows)

            elements = []

            # Extract data - Including container_type extraction
            ASSLY = str(row[found_columns.get('ASSLY', '')]) if 'ASSLY' in found_columns else "N/A"
            part_no = str(row[found_columns.get('part_no', '')]) if 'part_no' in found_columns else "N/A"
            desc = str(row[found_columns.get('description', '')]) if 'description' in found_columns else "N/A"
            Part_per_veh = str(row[found_columns.get('Part_per_veh', '')]) if 'Part_per_veh' in found_columns and pd.notna(row[found_columns['Part_per_veh']]) else ""
            container_type = str(row[found_columns.get('container_type', '')]) if 'container_type' in found_columns and pd.notna(row[found_columns['container_type']]) else ""
            Type = str(row[found_columns.get('Type', '')]) if 'Type' in found_columns and pd.notna(row[found_columns['Type']]) else ""
            line_location_raw = str(row[found_columns.get('line_location', '')]) if 'line_location' in found_columns and pd.notna(row[found_columns['line_location']]) else ""
            part_status = str(row[found_columns.get('part_status', '')]) if 'part_status' in found_columns and pd.notna(row[found_columns['part_status']]) else ""
            location_boxes = parse_line_location(line_location_raw)

            # Generate QR code - Including container_type in QR data
            qr_data = f"ASSLY: {ASSLY}\nPart No: {part_no}\nDescription: {desc}\n"
            if Part_per_veh:
                qr_data += f"QTY/VEH: {Part_per_veh}\n"
            if container_type:
                qr_data += f"Container Type: {container_type}\n"
            if Type:
                qr_data += f"Type: {Type}\n"
            if part_status:
                qr_data += f"Part Status: {part_status}\n"
            if line_location_raw:
                qr_data += f"Line Location: {line_location_raw}\n"
            qr_data += f"Date: {today_date}"

            qr_image = generate_qr_code(qr_data)
            if qr_image:
                qr_cell = qr_image
            else:
                qr_cell = Paragraph("QR", ParagraphStyle(name='QRPlaceholder', fontName='Helvetica-Bold', fontSize=12, alignment=TA_CENTER))

            # Row heights
            ASSLY_row_height = 0.85*cm
            part_row_height = 0.8*cm   
            desc_row_height = 0.5*cm
            bottom_row_height = 0.6*cm
            location_row_height = 0.5*cm

            # Process line location boxes
            location_box_1 = Paragraph(location_boxes[0], location_style) if location_boxes[0] else ""
            location_box_2 = Paragraph(location_boxes[1], location_style) if location_boxes[1] else ""
            location_box_3 = Paragraph(location_boxes[2], location_style) if location_boxes[2] else ""
            location_box_4 = Paragraph(location_boxes[3], location_style) if location_boxes[3] else ""

            # Create ASSLY row content
            first_box_content = first_box_logo if first_box_logo else ""

            # Column widths
            col_widths_assly = [
                content_width * 0.25,    # Logo box: 25%
                content_width * 0.15,    # Header: 15%
                content_width * 0.60     # Value: 60%
            ]

            # Column widths for 3-column PART NO row
            col_widths_partno = [
                content_width * 0.25,    # Header: 25%
                content_width * 0.50,    # Part number: 50%
                content_width * 0.25     # Part status: 25%
            ]

            col_widths_standard = [content_width * 0.25, content_width * 0.75]
            
            # Column widths for the main section with QR code spanning from QTY/VEH to DATE
            col_widths_with_qr = [
                content_width * 0.20,    # Header: 20%
                content_width * 0.20,    # First value: 20%
                content_width * 0.20,    # Second value: 20%
                content_width * 0.40     # QR code: 40%
            ]
            
            col_widths_bottom = [
                content_width * line_loc_header_width,
                content_width * line_loc_box1_width,
                content_width * line_loc_box2_width,
                content_width * line_loc_box3_width,
                content_width * line_loc_box4_width
            ]

            # Create individual tables for better control
            # ASSLY table
            assly_table_data = [[first_box_content, "ASSLY", Paragraph(ASSLY, ASSLY_style)]]
            assly_table = Table(assly_table_data, colWidths=col_widths_assly, rowHeights=[ASSLY_row_height])
            
            # PART NO table
            partno_table_data = [["PART NO", Paragraph(f"<b>{part_no}</b>", Part_style), Paragraph(f"<b>{part_status}</b>", Part_status_style)]]
            partno_table = Table(partno_table_data, colWidths=col_widths_partno, rowHeights=[part_row_height])
            
            # PART DESC table
            desc_table_data = [["PART DESC", Paragraph(desc, desc_style)]]
            desc_table = Table(desc_table_data, colWidths=col_widths_standard, rowHeights=[desc_row_height])
            
            # Main table with QR code spanning from QTY/VEH to DATE
            main_table_data = [
                ["QTY/VEH", Paragraph(str(Part_per_veh), partper_style), Paragraph(str(container_type), container_style), qr_cell],
                ["TYPE", Paragraph(str(Type), Type_style), "", ""],  # Empty cells where QR spans
                ["DATE", Paragraph(today_date, date_style), "", ""]   # Empty cells where QR spans
            ]
            main_table = Table(main_table_data, colWidths=col_widths_with_qr, rowHeights=[bottom_row_height, bottom_row_height, bottom_row_height])
            
            # LINE LOCATION table
            location_table_data = [["LINE LOCATION", location_box_1, location_box_2, location_box_3, location_box_4]]
            location_table = Table(location_table_data, colWidths=col_widths_bottom, rowHeights=[location_row_height])

            # Apply table styles
            assly_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),
                ('ALIGN', (1, 0), (1, 0), 'CENTER'),
                ('ALIGN', (2, 0), (2, 0), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            partno_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (0, 0), 8),
                ('FONTSIZE', (1, 0), (1, 0), 11),
                ('FONTSIZE', (2, 0), (2, 0), 9),
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('ALIGN', (2, 0), (2, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            desc_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (0, -1), 8),
                ('FONTSIZE', (1, 0), (-1, 0), 7),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Main table style with QR code spanning
            main_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),  # Headers bold
                ('FONTSIZE', (0, 0), (0, -1), 8),                # Header font size
                ('FONTSIZE', (1, 0), (2, -1), 10),               # Value font size
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),            # Headers centered
                ('ALIGN', (1, 0), (2, -1), 'LEFT'),              # Values left
                ('ALIGN', (3, 0), (3, 0), 'CENTER'),             # QR centered
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                # Grid for the left side (headers and values)
                ('GRID', (0, 0), (2, -1), 1, colors.black),
                # QR code spanning from row 0 to row 2 in column 3
                ('SPAN', (3, 0), (3, 2)),
                # QR code cell borders
                ('LINEBEFORE', (3, 0), (3, 0), 1, colors.black),
                ('LINEAFTER', (3, 0), (3, 0), 1, colors.black),
                ('LINEABOVE', (3, 0), (3, 0), 1, colors.black),
                ('LINEBELOW', (3, 2), (3, 2), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            location_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Apply styles to tables
            assly_table.setStyle(TableStyle(assly_table_style))
            partno_table.setStyle(TableStyle(partno_table_style))
            desc_table.setStyle(TableStyle(desc_table_style))
            main_table.setStyle(TableStyle(main_table_style))
            location_table.setStyle(TableStyle(location_table_style))

            # Add tables to elements
            elements.extend([
                assly_table,
                partno_table,
                desc_table,
                main_table,
                location_table
            ])

            # Add to all elements
            all_elements.extend(elements)
            if index < len(df) - 1:  # Add page break except for last item
                all_elements.append(PageBreak())

        progress_bar.empty()

        # Build PDF with border
        doc.build(all_elements, onFirstPage=draw_border, onLaterPages=draw_border)

        # Read PDF file for download
        with open(output_pdf_path, 'rb') as pdf_file:
            pdf_bytes = pdf_file.read()

        # Clean up temporary file
        os.unlink(output_pdf_path)

        return pdf_bytes, output_pdf_path

    except Exception as e:
        st.error(f"Error generating sticker labels: {str(e)}")
        return None, None

def main():
    st.set_page_config(page_title="Sticker Generator", layout="wide")
    st.title("Sticker Label Generator with QR Code")
    st.markdown("---")

    # File upload
    uploaded_file = st.file_uploader("Upload CSV file", type=['csv'])
    
    # Logo upload for first box
    st.subheader("Logo Settings")
    uploaded_first_box_logo = st.file_uploader(
        "Upload logo for first box (Optional)", 
        type=['png', 'jpg', 'jpeg'],
        help="Upload a logo to display in the first box of each sticker. Logo will be automatically resized to fit."
    )

    if uploaded_file is not None:
        try:
            # Read CSV
            df = pd.read_csv(uploaded_file)
            
            st.success(f"✅ File uploaded successfully! Found {len(df)} rows and {len(df.columns)} columns.")
            
            # Show preview of data
            st.subheader("Data Preview")
            st.dataframe(df.head())
            
            # Column settings
            st.subheader("Line Location Column Width Settings")
            st.info("Adjust the width percentages for Line Location columns. Total should equal 100%.")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                line_loc_header_width = st.slider("Header Width (%)", 15, 40, 25) / 100
            with col2:
                line_loc_box1_width = st.slider("Box 1 Width (%)", 10, 30, 18) / 100
            with col3:
                line_loc_box2_width = st.slider("Box 2 Width (%)", 10, 30, 18) / 100
            with col4:
                line_loc_box3_width = st.slider("Box 3 Width (%)", 10, 30, 18) / 100
            with col5:
                line_loc_box4_width = st.slider("Box 4 Width (%)", 10, 30, 21) / 100
            
            # Check if total equals 100%
            total_width = (line_loc_header_width + line_loc_box1_width + 
                          line_loc_box2_width + line_loc_box3_width + line_loc_box4_width)
            
            if abs(total_width - 1.0) > 0.01:  # Allow small rounding errors
                st.warning(f"⚠️ Total width is {total_width*100:.1f}%. Please adjust to make it 100%.")
            else:
                st.success(f"✅ Total width: {total_width*100:.1f}%")
            
            # Show detected columns
            st.subheader("Column Detection")
            
            # Define column mappings for display
            column_mappings = {
                'ASSLY': ['assly', 'ASSY NAME', 'Assy Name', 'assy name', 'assyname',
                         'assy_name', 'Assy_name', 'Assembly', 'Assembly Name', 'ASSEMBLY', 'Assembly_Name'],
                'Part Number': ['PARTNO', 'PARTNO.', 'Part No', 'Part Number', 'PartNo',
                               'partnumber', 'part no', 'partnum', 'PART', 'part', 'Product Code',
                               'Item Number', 'Item ID', 'Item No', 'item', 'Item'],
                'Description': ['DESCRIPTION', 'Description', 'Desc', 'Part Description',
                               'ItemDescription', 'item description', 'Product Description',
                               'Item Description', 'NAME', 'Item Name', 'Product Name'],
                'Qty per Vehicle': ['QYT', 'QTY / VEH', 'Qty/Veh', 'Qty Bin', 'Quantity per Bin',
                                   'qty bin', 'qtybin', 'quantity bin', 'BIN QTY', 'BINQTY',
                                   'QTY_BIN', 'QTY_PER_BIN', 'Bin Quantity', 'BIN'],
                'Container Type': ['CONTAINER', 'Container', 'container', 'BIN TYPE', 'Bin Type',
                                  'bin type', 'bintype', 'BINTYPE', 'Container Type', 'container type',
                                  'CONTAINER_TYPE', 'container_type', 'ContainerType'],
                'Type': ['TYPE', 'type', 'Type', 'tyPe', 'Type name'],
                'Line Location': ['LINE LOCATION', 'Line Location', 'line location', 'LINELOCATION',
                                 'linelocation', 'Line_Location', 'line_location', 'LINE_LOCATION',
                                 'LineLocation', 'line_loc', 'lineloc', 'LINELOC', 'Line Loc'],
                'Part Status': ['PART STATUS', 'Part Status', 'part status', 'PARTSTATUS',
                               'partstatus', 'Part_Status', 'part_status', 'PART_STATUS',
                               'PartStatus', 'STATUS', 'Status', 'status', 'Item Status',
                               'Component Status', 'Part State', 'State']
            }
            
            # Check which columns were found
            detected_cols = []
            for display_name, possible_names in column_mappings.items():
                found_col = find_column(df, possible_names)
                if found_col:
                    detected_cols.append(f"✅ **{display_name}**: `{found_col}`")
                else:
                    detected_cols.append(f"❌ **{display_name}**: Not found")
            
            # Display in columns for better layout
            col1, col2 = st.columns(2)
            with col1:
                for i in range(0, len(detected_cols), 2):
                    st.markdown(detected_cols[i])
            with col2:
                for i in range(1, len(detected_cols), 2):
                    if i < len(detected_cols):
                        st.markdown(detected_cols[i])
            
            # Generate button
            st.markdown("---")
            if st.button("🏷️ Generate Sticker Labels", type="primary", use_container_width=True):
                if abs(total_width - 1.0) > 0.01:
                    st.error("❌ Please adjust line location column widths to total 100% before generating.")
                else:
                    with st.spinner("Generating sticker labels... Please wait."):
                        pdf_bytes, pdf_path = generate_sticker_labels(
                            df, 
                            line_loc_header_width, 
                            line_loc_box1_width,
                            line_loc_box2_width, 
                            line_loc_box3_width, 
                            line_loc_box4_width,
                            uploaded_first_box_logo
                        )
                        
                        if pdf_bytes:
                            st.success("✅ Sticker labels generated successfully!")
                            
                            # Create download button
                            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"sticker_labels_{timestamp}.pdf"
                            
                            st.download_button(
                                label="📥 Download PDF",
                                data=pdf_bytes,
                                file_name=filename,
                                mime="application/pdf",
                                use_container_width=True
                            )
                            
                            # Show statistics
                            st.info(f"📊 Generated {len(df)} sticker labels")
                        else:
                            st.error("❌ Failed to generate sticker labels. Please check your data and try again.")
            
        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
            st.info("Please make sure your CSV file is properly formatted and contains the required columns.")
    
    else:
        st.info("👆 Please upload a CSV file to get started.")
        
        # Show example of expected CSV format
        st.subheader("Expected CSV Format")
        st.markdown("Your CSV file should contain columns with names similar to these:")
        
        example_data = {
            'ASSY NAME': ['Assembly 1', 'Assembly 2'],
            'PARTNO': ['P001', 'P002'],
            'DESCRIPTION': ['Part Description 1', 'Part Description 2'],
            'QTY / VEH': [5, 10],
            'CONTAINER': ['Box', 'Bin'],
            'TYPE': ['Type A', 'Type B'],
            'LINE LOCATION': ['A1_B2_C3_D4', 'E5_F6_G7_H8'],
            'PART STATUS': ['Active', 'Active']
        }
        
        example_df = pd.DataFrame(example_data)
        st.dataframe(example_df)
        
        st.markdown("""
        **Notes:**
        - Column names are case-insensitive and flexible (e.g., 'Part No', 'PartNo', 'PARTNO' will all work)
        - Required columns: Assembly name, Part number, Description
        - Optional columns: Quantity, Container type, Type, Line location, Part status
        - Line location should be in format: Location1_Location2_Location3_Location4
        """)

if __name__ == "__main__":
    main()

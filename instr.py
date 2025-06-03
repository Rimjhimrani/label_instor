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

            # Column widths for different sections
            col_widths_assly = [
                content_width * 0.25,    # Logo box: 25%
                content_width * 0.15,    # Header: 15%
                content_width * 0.60     # Value: 60%
            ]

            col_widths_partno = [
                content_width * 0.25,    # Header: 25%
                content_width * 0.50,    # Part number: 50%
                content_width * 0.25     # Part status: 25%
            ]

            col_widths_standard = [content_width * 0.25, content_width * 0.75]
            
            # For the combined bottom section with QR code
            col_widths_bottom_section = [
                content_width * 0.60,    # Left section (75% of 80%): 60%
                content_width * 0.40     # QR code section: 40%
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
            
            # Create combined bottom section table with QR code spanning 3 rows
            # Left section contains QTY/VEH, TYPE, and DATE in nested table
            left_section_data = [
                ["QTY/VEH", Paragraph(str(Part_per_veh), partper_style), Paragraph(str(container_type), container_style)],
                ["TYPE", Paragraph(str(Type), Type_style), ""],
                ["DATE", Paragraph(today_date, date_style), ""]
            ]
            
            # Column widths for the left section (nested table)
            left_section_col_widths = [
                (content_width * 0.60) * 0.42,  # Header: 42% of left section
                (content_width * 0.60) * 0.29,  # First value: 29% of left section  
                (content_width * 0.60) * 0.29   # Second value: 29% of left section
            ]
            
            left_section_table = Table(left_section_data, 
                                     colWidths=left_section_col_widths, 
                                     rowHeights=[bottom_row_height, bottom_row_height, bottom_row_height])
            
            # Main bottom section table combining left section and QR code
            bottom_section_data = [[left_section_table, qr_cell]]
            bottom_section_table = Table(bottom_section_data, 
                                       colWidths=col_widths_bottom_section, 
                                       rowHeights=[bottom_row_height * 3])  # 3 rows height for QR spanning
            
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

            # Left section table style (nested table)
            left_section_table_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),  # Headers bold
                ('FONTSIZE', (0, 0), (0, -1), 8),                # Header font size
                ('FONTSIZE', (1, 0), (-1, -1), 9),               # Value font size
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),            # Headers centered
                ('ALIGN', (1, 0), (-1, -1), 'LEFT'),             # Values left
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Bottom section table style (main table with QR)
            bottom_section_table_style = [
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, 0), 'CENTER'),  # QR code centered
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
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
            left_section_table.setStyle(TableStyle(left_section_table_style))
            bottom_section_table.setStyle(TableStyle(bottom_section_table_style))
            location_table.setStyle(TableStyle(location_table_style))

            # Add tables to elements
            elements.extend([
                assly_table,
                partno_table,
                desc_table,
                bottom_section_table,  # This replaces the separate qty, type, and date tables
                location_table,
                Spacer(1, 0.1*cm)
            ])

            # Add all elements for this sticker
            all_elements.extend(elements)
            
            # Add page break for next sticker (except for last one)
            if index < len(df) - 1:
                all_elements.append(PageBreak())

        # Build PDF
        try:
            doc.build(all_elements, onFirstPage=draw_border, onLaterPages=draw_border)
            
            # Read the generated PDF
            with open(output_pdf_path, 'rb') as pdf_file:
                pdf_data = pdf_file.read()
            
            # Clean up temporary file
            os.unlink(output_pdf_path)
            
            progress_bar.progress(1.0)
            st.success(f"✅ Successfully generated {len(df)} sticker labels!")
            
            return pdf_data, f"sticker_labels_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            
        except Exception as e:
            st.error(f"Error building PDF: {e}")
            # Clean up temporary file if it exists
            if os.path.exists(output_pdf_path):
                os.unlink(output_pdf_path)
            return None, None
            
    except Exception as e:
        st.error(f"Error in generate_sticker_labels: {e}")
        return None, None

def main():
    st.set_page_config(page_title="Sticker Label Generator", layout="wide")
    
    st.title("🏷️ Sticker Label Generator")
    st.markdown("Upload your Excel/CSV file to generate professional sticker labels with QR codes")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Logo upload section
        st.subheader("📷 Logo Upload")
        uploaded_logo = st.file_uploader(
            "Upload Logo for First Box (Optional)",
            type=['png', 'jpg', 'jpeg', 'gif'],
            help="Logo will be resized to fit in the first box (23% width)"
        )
        
        if uploaded_logo:
            st.success("✅ Logo uploaded successfully")
            # Show preview
            logo_preview = PILImage.open(uploaded_logo)
            st.image(logo_preview, caption="Logo Preview", width=150)
            uploaded_logo.seek(0)  # Reset file pointer
        
        st.divider()
        
        # Line location column width settings
        st.subheader("📏 Line Location Column Widths")
        st.markdown("Adjust the width percentages for line location columns:")
        
        line_loc_header_width = st.slider(
            "Header Width (%)", 
            min_value=0.05, 
            max_value=0.50, 
            value=0.20, 
            step=0.01,
            format="%.2f",
            help="Width of 'LINE LOCATION' header column"
        )
        
        remaining_width = 1.0 - line_loc_header_width
        st.caption(f"Remaining width for boxes: {remaining_width:.2f}")
        
        line_loc_box1_width = st.slider(
            "Box 1 Width (%)", 
            min_value=0.05, 
            max_value=remaining_width, 
            value=min(0.20, remaining_width/4), 
            step=0.01,
            format="%.2f"
        )
        
        remaining_after_box1 = remaining_width - line_loc_box1_width
        line_loc_box2_width = st.slider(
            "Box 2 Width (%)", 
            min_value=0.05, 
            max_value=remaining_after_box1, 
            value=min(0.20, remaining_after_box1/3), 
            step=0.01,
            format="%.2f"
        )
        
        remaining_after_box2 = remaining_after_box1 - line_loc_box2_width
        line_loc_box3_width = st.slider(
            "Box 3 Width (%)", 
            min_value=0.05, 
            max_value=remaining_after_box2, 
            value=min(0.20, remaining_after_box2/2), 
            step=0.01,
            format="%.2f"
        )
        
        line_loc_box4_width = remaining_after_box2 - line_loc_box3_width
        st.caption(f"Box 4 Width: {line_loc_box4_width:.2f} (auto-calculated)")
        
        # Validation
        total_width = (line_loc_header_width + line_loc_box1_width + 
                      line_loc_box2_width + line_loc_box3_width + line_loc_box4_width)
        
        if abs(total_width - 1.0) > 0.01:
            st.error(f"⚠️ Total width: {total_width:.2f} (should be 1.00)")
        else:
            st.success(f"✅ Total width: {total_width:.2f}")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📁 File Upload")
        uploaded_file = st.file_uploader(
            "Choose Excel or CSV file",
            type=['xlsx', 'xls', 'csv'],
            help="Upload your data file containing part information"
        )
        
        if uploaded_file is not None:
            try:
                # Read the file
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                st.success(f"✅ Successfully generated {len(df)} sticker labels!")
            
            return pdf_data, f"sticker_labels_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            
        except Exception as e:
            st.error(f"Error building PDF: {e}")
            # Clean up temporary file if it exists
            if os.path.exists(output_pdf_path):
                os.unlink(output_pdf_path)
            return None, None
            
    except Exception as e:
        st.error(f"Error in generate_sticker_labels: {e}")
        return None, None

def main():
    st.set_page_config(page_title="Sticker Label Generator", layout="wide")
    
    st.title("🏷️ Sticker Label Generator")
    st.markdown("Upload your Excel/CSV file to generate professional sticker labels with QR codes")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Logo upload section
        st.subheader("📷 Logo Upload")
        uploaded_logo = st.file_uploader(
            "Upload Logo for First Box (Optional)",
            type=['png', 'jpg', 'jpeg', 'gif'],
            help="Logo will be resized to fit in the first box (23% width)"
        )
        
        if uploaded_logo:
            st.success("✅ Logo uploaded successfully")
            # Show preview
            logo_preview = PILImage.open(uploaded_logo)
            st.image(logo_preview, caption="Logo Preview", width=150)
            uploaded_logo.seek(0)  # Reset file pointer
        
        st.divider()
        
        # Line location column width settings
        st.subheader("📏 Line Location Column Widths")
        st.markdown("Adjust the width percentages for line location columns:")
        
        line_loc_header_width = st.slider(
            "Header Width (%)", 
            min_value=0.05, 
            max_value=0.50, 
            value=0.20, 
            step=0.01,
            format="%.2f",
            help="Width of 'LINE LOCATION' header column"
        )
        
        remaining_width = 1.0 - line_loc_header_width
        st.caption(f"Remaining width for boxes: {remaining_width:.2f}")
        
        line_loc_box1_width = st.slider(
            "Box 1 Width (%)", 
            min_value=0.05, 
            max_value=remaining_width, 
            value=min(0.20, remaining_width/4), 
            step=0.01,
            format="%.2f"
        )
        
        remaining_after_box1 = remaining_width - line_loc_box1_width
        line_loc_box2_width = st.slider(
            "Box 2 Width (%)", 
            min_value=0.05, 
            max_value=remaining_after_box1, 
            value=min(0.20, remaining_after_box1/3), 
            step=0.01,
            format="%.2f"
        )
        
        remaining_after_box2 = remaining_after_box1 - line_loc_box2_width
        line_loc_box3_width = st.slider(
            "Box 3 Width (%)", 
            min_value=0.05, 
            max_value=remaining_after_box2, 
            value=min(0.20, remaining_after_box2/2), 
            step=0.01,
            format="%.2f"
        )
        
        line_loc_box4_width = remaining_after_box2 - line_loc_box3_width
        st.caption(f"Box 4 Width: {line_loc_box4_width:.2f} (auto-calculated)")
        
        # Validation
        total_width = (line_loc_header_width + line_loc_box1_width + 
                      line_loc_box2_width + line_loc_box3_width + line_loc_box4_width)
        
        if abs(total_width - 1.0) > 0.01:
            st.error(f"⚠️ Total width: {total_width:.2f} (should be 1.00)")
        else:
            st.success(f"✅ Total width: {total_width:.2f}")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📁 File Upload")
        uploaded_file = st.file_uploader(
            "Choose Excel or CSV file",
            type=['xlsx', 'xls', 'csv'],
            help="Upload your data file containing part information"
        )
        
        if uploaded_file is not None:
            try:
                # Read the file
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                st.success(f"✅ File loaded successfully! ({len(df)} rows)")
                
                # Show data preview
                with st.expander("📊 Data Preview", expanded=True):
                    st.dataframe(df.head(10), use_container_width=True)
                    st.caption(f"Showing first 10 rows of {len(df)} total rows")
                
                # Show column mapping
                with st.expander("🔗 Column Mapping", expanded=False):
                    st.markdown("**Detected columns and their mappings:**")
                    
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
                    
                    for field, possible_names in column_mappings.items():
                        found_col = find_column(df, possible_names)
                        if found_col:
                            st.success(f"✅ **{field}**: `{found_col}`")
                        else:
                            status = "❌ **Required**" if field in ['ASSLY', 'part_no', 'description'] else "⚠️ Optional"
                            st.write(f"{status} **{field}**: Not found")
                
                # Generate button
                st.header("🚀 Generate Labels")
                
                if st.button("Generate Sticker Labels", type="primary", use_container_width=True):
                    with st.spinner("Generating sticker labels... Please wait..."):
                        pdf_data, filename = generate_sticker_labels(
                            df, 
                            line_loc_header_width,
                            line_loc_box1_width,
                            line_loc_box2_width, 
                            line_loc_box3_width,
                            line_loc_box4_width,
                            uploaded_logo
                        )
                        
                        if pdf_data and filename:
                            st.balloons()
                            
                            # Download button
                            st.download_button(
                                label="📥 Download PDF Labels",
                                data=pdf_data,
                                file_name=filename,
                                mime="application/pdf",
                                use_container_width=True
                            )
                            
                            st.success("🎉 Labels generated successfully! Click the download button above.")
                        else:
                            st.error("❌ Failed to generate labels. Please check your data and try again.")
                            
            except Exception as e:
                st.error(f"❌ Error processing file: {e}")
                st.info("💡 Please ensure your file contains the required columns: ASSLY, Part No, and Description")
    
    with col2:
        st.header("ℹ️ Information")
        
        st.markdown("""
        ### 📋 Required Columns
        - **ASSLY/Assembly**: Assembly name
        - **Part No/Part Number**: Part identifier  
        - **Description**: Part description
        
        ### 📋 Optional Columns
        - **QTY/VEH**: Quantity per vehicle
        - **Container Type**: Bin/container type
        - **Type**: Part type
        - **Line Location**: Location code (format: A_B_C_D)
        - **Part Status**: Status information
        
        ### 📏 Label Specifications
        - **Size**: 10cm × 15cm
        - **Content Box**: 9.8cm × 5cm  
        - **QR Code**: Includes all part data
        - **Border**: Black border around content
        
        ### 🔧 Features
        - Automatic column detection
        - QR code generation
        - Logo support (23% width)
        - Customizable line location widths
        - Professional PDF output
        """)
        
        # Sample data download
        st.header("📄 Sample Data")
        sample_data = {
            'ASSLY': ['ENGINE_BLOCK', 'TRANSMISSION', 'BRAKE_SYSTEM'],
            'PARTNO': ['ENG001', 'TRN002', 'BRK003'],
            'DESCRIPTION': ['Engine Block Assembly', 'Automatic Transmission', 'Brake Disc Assembly'],
            'QTY / VEH': [1, 1, 4],
            'CONTAINER': ['Large Bin', 'Medium Bin', 'Small Bin'],
            'TYPE': ['Critical', 'Standard', 'Standard'],
            'LINE LOCATION': ['A1_B2_C3_D4', 'X1_Y2_Z3_W4', 'P1_Q2_R3_S4'],
            'PART STATUS': ['Active', 'Active', 'Pending']
        }
        
        sample_df = pd.DataFrame(sample_data)
        
        # Create Excel file in memory
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            sample_df.to_excel(writer, index=False, sheet_name='Sample Data')
        excel_buffer.seek(0)
        
        col_sample1, col_sample2 = st.columns(2)
        
        with col_sample1:
            st.download_button(
                label="📥 Download Sample Excel",
                data=excel_buffer.getvalue(),
                file_name="sample_sticker_data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Download a sample Excel file to see the expected format"
            )
        
        with col_sample2:
            st.download_button(
                label="📥 Download Sample CSV",
                data=sample_df.to_csv(index=False).encode('utf-8'),
                file_name="sample_sticker_data.csv",
                mime="text/csv",
                help="Download a sample CSV file to see the expected format"
            )

if __name__ == "__main__":
    main()

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

            # Create table data with QR code spanning QTY/VEH to TYPE rows
            # Structure: Modified to have 3 columns for DATE row (25%, 35%, 40%)
            unified_table_data = [
                [first_box_content, "ASSLY", Paragraph(ASSLY, ASSLY_style), ""],
                ["PART NO", Paragraph(f"<b>{part_no}</b>", Part_style), Paragraph(f"<b>{part_status}</b>", Part_status_style), ""],
                ["PART DESC", Paragraph(desc, desc_style), "", ""],
                ["QTY/VEH", Paragraph(str(Part_per_veh), partper_style), Paragraph(str(container_type), container_style), qr_cell],
                ["TYPE", Paragraph(str(Type), Type_style), "", ""],
                ["DATE", Paragraph(today_date, date_style), qr_cell],  # 3-column structure: header (25%), value (35%), QR spans (40%)
                ["LINE LOCATION", location_box_1, location_box_2, location_box_3, location_box_4]
            ]

            # Column widths for different sections
            col_widths_standard_4col = [
                content_width * 0.25,    # Header: 25%
                content_width * 0.35,    # Content: 35%
                content_width * 0.00,    # Empty for QR alignment: 0%
                content_width * 0.40     # QR area: 40%
            ]

            col_widths_qty_4col = [
                content_width * 0.25,    # Header: 25%
                content_width * 0.175,   # QTY value: 17.5%
                content_width * 0.175,   # Container: 17.5%
                content_width * 0.40     # QR code: 40%
            ]

            # New 3-column structure for DATE row (25%, 35%, 40%)
            col_widths_date_3col = [
                content_width * 0.25,    # Header: 25%
                content_width * 0.35,    # Date value: 35%
                content_width * 0.40     # QR code: 40%
            ]

            col_widths_bottom = [
                content_width * line_loc_header_width,
                content_width * line_loc_box1_width,
                content_width * line_loc_box2_width,
                content_width * line_loc_box3_width,
                content_width * line_loc_box4_width
            ]

            row_heights = [ASSLY_row_height, part_row_height, desc_row_height, bottom_row_height, bottom_row_height, bottom_row_height, location_row_height]

            # Create the main table with all rows
            main_table = Table(unified_table_data, colWidths=col_widths_standard_4col, rowHeights=row_heights)

            # Apply comprehensive table style with QR spanning from row 3 (QTY/VEH) to row 4 (TYPE)
            # DATE row now has its own QR cell without spanning
            main_table_style = [
                # Font settings
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (1, 6), 'Helvetica-Bold'),  # Headers bold
                ('FONTNAME', (1, 1), (1, 1), 'Helvetica-Bold'),  # Part number bold
                ('FONTNAME', (2, 1), (2, 1), 'Helvetica-Bold'),  # Part status bold
                
                # Font sizes
                ('FONTSIZE', (0, 0), (1, 6), 8),                # Header font size
                ('FONTSIZE', (2, 0), (2, 0), 9),                # ASSLY content
                ('FONTSIZE', (1, 1), (1, 1), 11),               # Part number
                ('FONTSIZE', (2, 1), (2, 1), 9),                # Part status
                ('FONTSIZE', (1, 2), (1, 2), 7),                # Description
                ('FONTSIZE', (1, 3), (2, 4), 10),               # QTY, Container, Type
                ('FONTSIZE', (1, 5), (1, 5), 10),               # Date
                ('FONTSIZE', (1, 6), (4, 6), 8),                # Line location
                
                # Alignment
                ('ALIGN', (0, 0), (0, 6), 'CENTER'),            # All headers centered
                ('ALIGN', (1, 0), (1, 0), 'CENTER'),            # ASSLY header centered
                ('ALIGN', (2, 0), (2, 0), 'LEFT'),              # ASSLY content left
                ('ALIGN', (1, 1), (1, 1), 'LEFT'),              # Part number left
                ('ALIGN', (2, 1), (2, 1), 'CENTER'),            # Part status centered
                ('ALIGN', (1, 2), (1, 2), 'LEFT'),              # Description left
                ('ALIGN', (1, 3), (2, 4), 'LEFT'),              # QTY, Container, Type left
                ('ALIGN', (3, 3), (3, 4), 'CENTER'),            # QR code centered (QTY-TYPE span)
                ('ALIGN', (1, 5), (1, 5), 'LEFT'),              # Date left
                ('ALIGN', (2, 5), (2, 5), 'CENTER'),            # Date QR centered
                ('ALIGN', (1, 6), (4, 6), 'CENTER'),            # Line location centered
                
                # Vertical alignment
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                
                # Grid lines - Full table grid
                ('GRID', (0, 0), (2, 6), 1, colors.black),      # Left side grid (all rows except QR area)
                ('GRID', (3, 3), (3, 4), 1, colors.black),      # QR cell borders (QTY-TYPE span)
                ('GRID', (2, 5), (2, 5), 1, colors.black),      # DATE QR cell border
                ('GRID', (0, 6), (4, 6), 1, colors.black),      # Line location row (5 columns)
                
                # QR code spanning from QTY/VEH (row 3) to TYPE (row 4)
                ('SPAN', (3, 3), (3, 4)),
                # DATE row has separate QR cell (no additional spanning needed)
                
                # Padding
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Apply the style to the main table
            main_table.setStyle(TableStyle(main_table_style))

            # Add the table to elements
            elements.append(main_table)

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
            st.success(f"✅ File uploaded successfully! Found {len(df)} rows.")

            # Display column info
            st.subheader("Column Information")
            st.write("**Available columns in your file:**")
            for i, col in enumerate(df.columns, 1):
                st.write(f"{i}. `{col}`")

            # Show data preview
            st.subheader("Data Preview")
            st.dataframe(df.head())

            # Line location width settings
            st.subheader("Line Location Box Width Settings")
            st.write("Adjust the width percentages for line location boxes (total should equal 1.0):")

            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                line_loc_header_width = st.number_input("Header Width", min_value=0.1, max_value=0.8, value=0.25, step=0.05)
            with col2:
                line_loc_box1_width = st.number_input("Box 1 Width", min_value=0.05, max_value=0.5, value=0.1875, step=0.05)
            with col3:
                line_loc_box2_width = st.number_input("Box 2 Width", min_value=0.05, max_value=0.5, value=0.1875, step=0.05)
            with col4:
                line_loc_box3_width = st.number_input("Box 3 Width", min_value=0.05, max_value=0.5, value=0.1875, step=0.05)
            with col5:
                line_loc_box4_width = st.number_input("Box 4 Width", min_value=0.05, max_value=0.5, value=0.1875, step=0.05)

            total_width = line_loc_header_width + line_loc_box1_width + line_loc_box2_width + line_loc_box3_width + line_loc_box4_width

            if abs(total_width - 1.0) > 0.01:
                st.warning(f"⚠️ Total width is {total_width:.3f}, should be 1.0")
                st.info("Adjusting widths proportionally...")
                # Auto-adjust proportionally
                line_loc_header_width = line_loc_header_width / total_width
                line_loc_box1_width = line_loc_box1_width / total_width
                line_loc_box2_width = line_loc_box2_width / total_width
                line_loc_box3_width = line_loc_box3_width / total_width
                line_loc_box4_width = line_loc_box4_width / total_width
                st.success(f"✅ Adjusted total width to 1.0")
            else:
                st.success(f"✅ Total width: {total_width:.3f}")

            # Generate button
            if st.button("🏷️ Generate Sticker Labels", type="primary"):
                with st.spinner("Generating sticker labels... This may take a few moments."):
                    pdf_bytes, _ = generate_sticker_labels(
                        df,
                        line_loc_header_width,
                        line_loc_box1_width,
                        line_loc_box2_width,
                        line_loc_box3_width,
                        line_loc_box4_width,
                        uploaded_first_box_logo
                    )

                    if pdf_bytes:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"sticker_labels_{timestamp}.pdf"

                        st.success("✅ Sticker labels generated successfully!")
                        st.download_button(
                            label="📥 Download PDF",
                            data=pdf_bytes,
                            file_name=filename,
                            mime="application/pdf"
                        )

                        # Display generation summary
                        st.info(f"📊 Generated {len(df)} sticker labels")
                        
                        # Show file size
                        file_size_mb = len(pdf_bytes) / (1024 * 1024)
                        st.info(f"📄 File size: {file_size_mb:.2f} MB")

                    else:
                        st.error("❌ Failed to generate sticker labels. Please check your data and try again.")

        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
            st.info("Please ensure your CSV file is properly formatted and contains the required columns.")

    else:
        st.info("👆 Please upload a CSV file to get started.")
        
        # Show help information
        with st.expander("ℹ️ Help & Column Requirements"):
            st.markdown("""
            ### Required Columns
            Your CSV file must contain these columns (names can vary):
            - **ASSLY/Assembly**: Assembly name or code
            - **Part No/Part Number**: Part number or product code  
            - **Description**: Part description or name
            
            ### Optional Columns
            - **QTY/VEH or Bin Qty**: Quantity per vehicle or bin
            - **Container Type**: Type of container or bin
            - **Type**: Part type or category
            - **Line Location**: Location code (will be split into 4 boxes using underscore separator)
            - **Part Status**: Status of the part
            
            ### Column Name Variations Supported
            The system automatically recognizes common variations of column names:
            - Part No: PARTNO, Part Number, PartNo, Item Number, etc.
            - Description: DESCRIPTION, Desc, Part Description, Item Name, etc.
            - Assembly: ASSLY, ASSY NAME, Assembly Name, etc.
            
            ### Line Location Format
            Line locations should be formatted as: `Location1_Location2_Location3_Location4`
            Example: `A1_B2_C3_D4`
            
            ### Logo Requirements
            - Supported formats: PNG, JPG, JPEG
            - Logo will be automatically resized to fit in the designated space
            - Transparent backgrounds will be converted to white
            """)

if __name__ == "__main__":
    main()

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
            box_size=10,  # Increased box size for better visibility
            border=2,
        )

        qr.add_data(data_string)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")

        img_buffer = BytesIO()
        qr_img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        # Larger QR code for better scanning
        return Image(img_buffer, width=2.2*cm, height=2.2*cm)
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
        # Define column mappings
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
            'Type': ['TYPE', 'type', 'Type', 'tyPe', 'Type name'],
            'line_location': ['LINE LOCATION', 'Line Location', 'line location', 'LINELOCATION',
                             'linelocation', 'Line_Location', 'line_location', 'LINE_LOCATION',
                             'LineLocation', 'line_loc', 'lineloc', 'LINELOC', 'Line Loc'],
            'part_status': ['PART STATUS', 'Part Status', 'part status', 'PARTSTATUS',
                           'partstatus', 'Part_Status', 'part_status', 'PART_STATUS',
                           'PartStatus', 'STATUS', 'Status', 'status', 'Item Status',
                           'Component Status', 'Part State', 'State'],
            'container_type': ['CONTAINER TYPE', 'Container Type', 'container type', 'CONTAINERTYPE',
                              'containertype', 'Container_Type', 'container_type', 'CONTAINER_TYPE',
                              'ContainerType', 'BIN TYPE', 'Bin Type', 'bin type', 'BINTYPE',
                              'bintype', 'Bin_Type', 'bin_type', 'BIN_TYPE', 'BinType',
                              'Container', 'Bin', 'CONTAINER', 'BIN', 'container', 'bin']
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
        container_style = ParagraphStyle(name='Container', fontName='Helvetica', fontSize=9, alignment=TA_CENTER, leading=12)
        Type_style = ParagraphStyle(name='Type', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        date_style = ParagraphStyle(name='DATE', fontName='Helvetica', fontSize=9, alignment=TA_LEFT, leading=12)
        location_style = ParagraphStyle(name='Location', fontName='Helvetica', fontSize=8, alignment=TA_CENTER, leading=10)

        content_width = CONTENT_BOX_WIDTH
        all_elements = []
        today_date = datetime.datetime.now().strftime("%d-%m-%Y")

        # Handle uploaded logo for first box
        first_box_logo = None
        if uploaded_first_box_logo is not None:
            logo_width_cm = (content_width * 0.25) / cm  # 25% of content width in cm
            logo_height_cm = 0.75  # 0.75cm height

            first_box_logo = process_uploaded_logo(uploaded_first_box_logo, logo_width_cm, logo_height_cm)
            if first_box_logo:
                st.success(f"✅ Logo processed - Size: {logo_width_cm:.2f}cm x {logo_height_cm:.2f}cm")
            else:
                st.error("❌ Failed to process uploaded logo")

        # Process each row
        total_rows = len(df)
        progress_bar = st.progress(0)

        for index, row in df.iterrows():
            progress_bar.progress((index + 1) / total_rows)

            elements = []

            # Extract data
            ASSLY = str(row[found_columns.get('ASSLY', '')]) if 'ASSLY' in found_columns else "N/A"
            part_no = str(row[found_columns.get('part_no', '')]) if 'part_no' in found_columns else "N/A"
            desc = str(row[found_columns.get('description', '')]) if 'description' in found_columns else "N/A"
            Part_per_veh = str(row[found_columns.get('Part_per_veh', '')]) if 'Part_per_veh' in found_columns and pd.notna(row[found_columns['Part_per_veh']]) else ""
            Type = str(row[found_columns.get('Type', '')]) if 'Type' in found_columns and pd.notna(row[found_columns['Type']]) else ""
            line_location_raw = str(row[found_columns.get('line_location', '')]) if 'line_location' in found_columns and pd.notna(row[found_columns['line_location']]) else ""
            part_status = str(row[found_columns.get('part_status', '')]) if 'part_status' in found_columns and pd.notna(row[found_columns['part_status']]) else ""
            container_type = str(row[found_columns.get('container_type', '')]) if 'container_type' in found_columns and pd.notna(row[found_columns['container_type']]) else ""
            location_boxes = parse_line_location(line_location_raw)

            # Generate QR code
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

            # Define column widths according to your specifications
            col_widths_standard = [content_width * 0.25, content_width * 0.75]
            col_widths_qty = [content_width * 0.25, content_width * 0.175, content_width * 0.175, content_width * 0.40]  # QTY/VEH row
            col_widths_middle = [content_width * 0.25, content_width * 0.35, content_width * 0.40]  # TYPE and DATE rows
            col_widths_location = [
                content_width * line_loc_header_width,
                content_width * line_loc_box1_width,
                content_width * line_loc_box2_width,
                content_width * line_loc_box3_width,
                content_width * line_loc_box4_width
            ]

            # Row heights - adjusted for better QR code visibility
            ASSLY_row_height = 0.85*cm
            part_row_height = 0.8*cm   
            desc_row_height = 0.5*cm
            qty_row_height = 0.75*cm  # Increased height for QR code row
            other_row_height = 0.6*cm
            location_row_height = 0.5*cm

            # Process line location boxes
            location_box_1 = Paragraph(location_boxes[0], location_style) if location_boxes[0] else ""
            location_box_2 = Paragraph(location_boxes[1], location_style) if location_boxes[1] else ""
            location_box_3 = Paragraph(location_boxes[2], location_style) if location_boxes[2] else ""
            location_box_4 = Paragraph(location_boxes[3], location_style) if location_boxes[3] else ""

            # Create ASSLY row content
            first_box_content = first_box_logo if first_box_logo else ""

            # Create the main content layout
            # Row 1: Logo/Empty | ASSLY Header | ASSLY Value (using standard 25-75 split)
            assly_table_data = [[first_box_content, "ASSLY", Paragraph(ASSLY, ASSLY_style)]]
            assly_col_widths = [content_width * 0.25, content_width * 0.15, content_width * 0.60]

            # Row 2: PART NO Header | Part Number | Part Status (using standard 25-50-25 split)
            partno_table_data = [["PART NO", Paragraph(f"<b>{part_no}</b>", Part_style), Paragraph(f"<b>{part_status}</b>", Part_status_style)]]
            partno_col_widths = [content_width * 0.25, content_width * 0.50, content_width * 0.25]

            # Row 3: PART DESC Header | Description (using standard 25-75 split)
            desc_table_data = [["PART DESC", Paragraph(desc, desc_style)]]
            desc_col_widths = col_widths_standard

            # Row 4: QTY/VEH with QR code - using special QTY layout
            # Layout: Header (25%) | QTY Value (17.5%) | Container Type (17.5%) | QR Code (40%)
            qty_table_data = [["QTY/VEH", Paragraph(str(Part_per_veh), partper_style), Paragraph(str(container_type), container_style), qr_cell]]
            qty_col_widths = col_widths_qty

            # Row 5: TYPE Header | Type Value | Empty (using middle layout 25-35-40)
            type_table_data = [["TYPE", Paragraph(str(Type), Type_style), ""]]
            type_col_widths = col_widths_middle

            # Row 6: DATE Header | Date Value | Empty (using middle layout 25-35-40)
            date_table_data = [["DATE", Paragraph(today_date, date_style), ""]]
            date_col_widths = col_widths_middle

            # Row 7: LINE LOCATION with 4 boxes (using custom location layout)
            location_table_data = [["LINE LOCATION", location_box_1, location_box_2, location_box_3, location_box_4]]
            location_col_widths = col_widths_location

            # Create individual tables
            assly_table = Table(assly_table_data, colWidths=assly_col_widths, rowHeights=[ASSLY_row_height])
            partno_table = Table(partno_table_data, colWidths=partno_col_widths, rowHeights=[part_row_height])
            desc_table = Table(desc_table_data, colWidths=desc_col_widths, rowHeights=[desc_row_height])
            qty_table = Table(qty_table_data, colWidths=qty_col_widths, rowHeights=[qty_row_height])
            type_table = Table(type_table_data, colWidths=type_col_widths, rowHeights=[other_row_height])
            date_table = Table(date_table_data, colWidths=date_col_widths, rowHeights=[other_row_height])
            location_table = Table(location_table_data, colWidths=location_col_widths, rowHeights=[location_row_height])

            # Define common table style elements
            common_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),  # First column bold (headers)
                ('FONTSIZE', (0, 0), (0, 0), 8),  # Header font size
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),  # Header alignment
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Apply styles to each table
            assly_table.setStyle(TableStyle(common_style + [
                ('ALIGN', (2, 0), (2, 0), 'LEFT'),  # ASSLY value left aligned
            ]))

            partno_table.setStyle(TableStyle(common_style + [
                ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),  # Part number bold
                ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),  # Part status bold
                ('FONTSIZE', (1, 0), (1, 0), 11),  # Part number font size
                ('FONTSIZE', (2, 0), (2, 0), 9),   # Part status font size
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),   # Part number left
                ('ALIGN', (2, 0), (2, 0), 'CENTER'), # Part status center
            ]))

            desc_table.setStyle(TableStyle(common_style + [
                ('FONTSIZE', (1, 0), (1, 0), 7),  # Description font size
                ('ALIGN', (1, 0), (1, 0), 'LEFT'), # Description left
            ]))

            qty_table.setStyle(TableStyle(common_style + [
                ('FONTSIZE', (1, 0), (2, 0), 9),    # QTY and Container font size
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),   # QTY value left
                ('ALIGN', (2, 0), (2, 0), 'CENTER'), # Container center
                ('ALIGN', (3, 0), (3, 0), 'CENTER'), # QR code center
                ('VALIGN', (3, 0), (3, 0), 'MIDDLE'), # QR code middle
            ]))

            type_table.setStyle(TableStyle(common_style + [
                ('FONTSIZE', (1, 0), (1, 0), 9),   # Type font size
                ('ALIGN', (1, 0), (1, 0), 'LEFT'), # Type left
            ]))

            date_table.setStyle(TableStyle(common_style + [
                ('FONTSIZE', (1, 0), (1, 0), 9),   # Date font size
                ('ALIGN', (1, 0), (1, 0), 'LEFT'), # Date left
            ]))

            location_table.setStyle(TableStyle(common_style + [
                ('FONTSIZE', (1, 0), (-1, 0), 8),    # Location boxes font size
                ('ALIGN', (1, 0), (-1, 0), 'CENTER'), # Location boxes center
            ]))

            # Add all tables to elements
            elements.extend([
                assly_table,
                partno_table,
                desc_table,
                qty_table,
                type_table,
                date_table,
                location_table
            ])

            # Add page break except for last row
            if index < len(df) - 1:
                elements.append(PageBreak())

            all_elements.extend(elements)

        progress_bar.empty()

        # Build PDF
        doc.build(all_elements, onFirstPage=draw_border, onLaterPages=draw_border)

        # Read the PDF file and return as bytes
        with open(output_pdf_path, 'rb') as f:
            pdf_bytes = f.read()

        # Clean up temporary file
        os.unlink(output_pdf_path)

        return pdf_bytes, f"sticker_labels_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    except Exception as e:
        st.error(f"Error generating sticker labels: {e}")
        return None, None


def main():
    st.set_page_config(page_title="Sticker Label Generator", layout="wide")
    
    st.title("🏷️ Sticker Label Generator")
    st.markdown("Generate professional sticker labels with QR codes from your Excel/CSV data")

    # File upload
    uploaded_file = st.file_uploader(
        "Upload your Excel or CSV file",
        type=['xlsx', 'xls', 'csv'],
        help="File should contain columns for Assembly, Part Number, Description, etc."
    )

    if uploaded_file is not None:
        try:
            # Read the file
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            st.success(f"✅ File loaded successfully! Found {len(df)} rows and {len(df.columns)} columns.")
            
            # Show column names
            st.subheader("📊 Data Preview")
            st.write("**Available Columns:**", list(df.columns))
            st.dataframe(df.head())

            # Configuration section
            st.subheader("⚙️ Configuration")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Line Location Box Widths** (should sum to 1.0)")
                line_loc_header_width = st.number_input("Header Width", min_value=0.1, max_value=0.5, value=0.25, step=0.05)
                line_loc_box1_width = st.number_input("Box 1 Width", min_value=0.1, max_value=0.3, value=0.1875, step=0.0125)
                line_loc_box2_width = st.number_input("Box 2 Width", min_value=0.1, max_value=0.3, value=0.1875, step=0.0125)
                line_loc_box3_width = st.number_input("Box 3 Width", min_value=0.1, max_value=0.3, value=0.1875, step=0.0125)
                line_loc_box4_width = st.number_input("Box 4 Width", min_value=0.1, max_value=0.3, value=0.1875, step=0.0125)
                
                total_width = line_loc_header_width + line_loc_box1_width + line_loc_box2_width + line_loc_box3_width + line_loc_box4_width
                if abs(total_width - 1.0) > 0.01:
                    st.warning(f"⚠️ Total width is {total_width:.3f}, should be 1.0")
                else:
                    st.success(f"✅ Total width: {total_width:.3f}")

            with col2:
                st.markdown("**Logo Upload (Optional)**")
                uploaded_logo = st.file_uploader(
                    "Upload logo for first box",
                    type=['png', 'jpg', 'jpeg'],
                    help="Logo will be resized to fit the first box (25% width, 0.75cm height)"
                )
                
                if uploaded_logo is not None:
                    st.success("✅ Logo uploaded successfully!")
                    # Show preview
                    logo_preview = PILImage.open(uploaded_logo)
                    st.image(logo_preview, caption="Logo Preview", width=200)

            # Layout information
            st.info("""
            **Layout Structure:**
            - **QTY/VEH Row**: Header (25%) | QTY Value (17.5%) | Container Type (17.5%) | QR Code (40%)
            - **Other Rows**: Header (25%) | Content (75%)
            - **Line Location**: Header (25%) | 4 Boxes (18.75% each)
            """)

            # Generate button
            if st.button("🏷️ Generate Sticker Labels", type="primary"):
                with st.spinner("Generating sticker labels..."):
                    pdf_bytes, filename = generate_sticker_labels(
                        df, 
                        line_loc_header_width, 
                        line_loc_box1_width,
                        line_loc_box2_width, 
                        line_loc_box3_width, 
                        line_loc_box4_width,
                        uploaded_logo
                    )
                    
                    if pdf_bytes:
                        st.success("✅ Sticker labels generated successfully!")
                        
                        # Download button
                        st.download_button(
                            label="📥 Download PDF",
                            data=pdf_bytes,
                            file_name=filename,
                            mime="application/pdf"
                        )
                        
                        # Show PDF preview (first page)
                        st.markdown("### 📄 PDF Preview")
                        st.markdown("*Click the download button above to get the complete PDF file.*")
                        
                    else:
                        st.error("❌ Failed to generate sticker labels. Please check your data and try again.")

        except Exception as e:
            st.error(f"❌ Error reading file: {e}")
            st.info("Please ensure your file is a valid Excel (.xlsx, .xls) or CSV (.csv) file.")

    else:
        # Instructions when no file is uploaded
        st.markdown("""
        ### 📝 Instructions:
        
        1. **Upload your data file** (Excel or CSV format)
        2. **Review the data preview** to ensure columns are detected correctly
        3. **Configure layout settings** if needed (optional)
        4. **Upload a logo** for the first box (optional)
        5. **Generate the sticker labels** and download the PDF
        
        ### 📋 Required Columns:
        Your file should contain these columns (case-insensitive):
        - **Assembly** (ASSLY, Assembly Name, etc.)
        - **Part Number** (PARTNO, Part No, Item Number, etc.)
        - **Description** (Description, Part Description, etc.)
        
        ### 🔧 Optional Columns:
        - **Quantity per Vehicle** (QTY/VEH, Qty Bin, etc.)
        - **Type** (Type, Type Name, etc.)
        - **Line Location** (Line Location, Line Loc, etc.)
        - **Part Status** (Part Status, Status, etc.)
        - **Container Type** (Container Type, Bin Type, etc.)
        
        ### 📏 Sticker Specifications:
        - **Size**: 10cm × 15cm
        - **Content Area**: 9.8cm × 5cm with border
        - **QR Code**: Contains all part information for easy scanning
        - **Professional layout** with clear typography and organized sections
        """)

if __name__ == "__main__":
    main()

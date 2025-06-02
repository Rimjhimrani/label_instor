, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            bottom_style = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),
                ('ALIGN', (1, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]

            # Apply styles to tables
            assly_table.setStyle(assly_style)
            partno_table.setStyle(partno_style)
            desc_table.setStyle(desc_style_table)
            qty_table.setStyle(qty_style)
            type_table.setStyle(type_style)
            date_table.setStyle(date_style_table)
            bottom_table.setStyle(bottom_style)

            # Add tables to elements
            elements.extend([
                assly_table,
                partno_table,
                desc_table,
                qty_table,
                type_table,
                date_table,
                bottom_table
            ])

            all_elements.extend(elements)
            if index < len(df) - 1:
                all_elements.append(PageBreak())

        progress_bar.empty()

        # Build PDF
        doc.build(all_elements, onFirstPage=draw_border, onLaterPages=draw_border)

        # Read the PDF file
        with open(output_pdf_path, 'rb') as f:
            pdf_data = f.read()

        # Clean up temporary file
        os.unlink(output_pdf_path)

        return pdf_data, f"sticker_labels_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    except Exception as e:
        st.error(f"Error generating sticker labels: {e}")
        return None, None

def main():
    st.set_page_config(page_title="Sticker Label Generator", layout="wide")
    
    st.title("🏷️ Sticker Label Generator")
    st.markdown("Generate professional sticker labels with QR codes from your Excel/CSV data")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("📊 Configuration")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Choose Excel/CSV file", 
            type=['xlsx', 'xls', 'csv'],
            help="Upload your data file containing part information"
        )
        
        # Logo upload
        st.subheader("🖼️ Logo Settings")
        uploaded_logo = st.file_uploader(
            "Upload Logo (Optional)", 
            type=['png', 'jpg', 'jpeg'],
            help="Logo will be placed in the first box of ASSLY row"
        )
        
        # Line location configuration
        st.subheader("📍 Line Location Layout")
        st.markdown("Configure the width percentages for line location boxes:")
        
        line_loc_header_width = st.slider("Header Width (%)", 10, 50, 25, 5) / 100
        line_loc_box1_width = st.slider("Box 1 Width (%)", 5, 30, 20, 5) / 100
        line_loc_box2_width = st.slider("Box 2 Width (%)", 5, 30, 20, 5) / 100
        line_loc_box3_width = st.slider("Box 3 Width (%)", 5, 30, 20, 5) / 100
        line_loc_box4_width = st.slider("Box 4 Width (%)", 5, 30, 15, 5) / 100
        
        # Validate total width
        total_width = (line_loc_header_width + line_loc_box1_width + 
                      line_loc_box2_width + line_loc_box3_width + line_loc_box4_width)
        
        if abs(total_width - 1.0) > 0.01:
            st.warning(f"⚠️ Total width: {total_width:.0%} (should be 100%)")
        else:
            st.success(f"✅ Total width: {total_width:.0%}")

    # Main content area
    if uploaded_file is not None:
        try:
            # Read the file
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.success(f"✅ File loaded successfully! Found {len(df)} rows")
            
            # Display preview
            with st.expander("📋 Data Preview", expanded=True):
                st.dataframe(df.head(10), use_container_width=True)
                st.info(f"Showing first 10 rows out of {len(df)} total rows")
            
            # Column mapping info
            with st.expander("🔍 Column Detection", expanded=False):
                st.markdown("### Detected Columns:")
                
                column_mappings = {
                    'ASSLY': ['assly', 'ASSY NAME', 'Assy Name', 'assy name', 'assyname'],
                    'Part Number': ['PARTNO', 'PARTNO.', 'Part No', 'Part Number', 'PartNo'],
                    'Description': ['DESCRIPTION', 'Description', 'Desc', 'Part Description'],
                    'Quantity per Vehicle': ['QYT', 'QTY / VEH', 'Qty/Veh', 'Qty Bin'],
                    'Type': ['TYPE', 'type', 'Type', 'tyPe', 'Type name'],
                    'Line Location': ['LINE LOCATION', 'Line Location', 'line location'],
                    'Part Status': ['PART STATUS', 'Part Status', 'part status'],
                    'Bin Type': ['BIN TYPE', 'Bin Type', 'bin type', 'BINTYPE']
                }
                
                for field, possible_names in column_mappings.items():
                    found_col = find_column(df, possible_names)
                    if found_col:
                        st.success(f"✅ {field}: `{found_col}`")
                    else:
                        st.error(f"❌ {field}: Not found")
            
            # Generate button
            st.markdown("---")
            col1, col2, col3 = st.columns([1, 2, 1])
            
            with col2:
                if st.button("🚀 Generate Sticker Labels", type="primary", use_container_width=True):
                    with st.spinner("Generating sticker labels... Please wait"):
                        pdf_data, filename = generate_sticker_labels(
                            df, 
                            line_loc_header_width,
                            line_loc_box1_width,
                            line_loc_box2_width, 
                            line_loc_box3_width,
                            line_loc_box4_width,
                            uploaded_logo
                        )
                        
                        if pdf_data:
                            st.success("✅ Stickers generated successfully!")
                            
                            # Download button
                            st.download_button(
                                label="📥 Download PDF",
                                data=pdf_data,
                                file_name=filename,
                                mime="application/pdf",
                                use_container_width=True
                            )
                            
                            # Display file info
                            st.info(f"📄 Generated {len(df)} sticker labels")
                        else:
                            st.error("❌ Failed to generate stickers. Please check your data and try again.")
        
        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
            st.markdown("**Please ensure your file contains the required columns:**")
            st.markdown("- ASSLY/Assembly Name")
            st.markdown("- Part Number/Part No")
            st.markdown("- Description/Part Description")
    
    else:
        # Welcome message
        st.markdown("""
        ### 📋 How to use:
        1. **Upload** your Excel or CSV file containing part data
        2. **Configure** line location box widths (optional)
        3. **Upload** a logo image (optional) 
        4. **Generate** professional sticker labels with QR codes
        
        ### 📊 Required Columns:
        - **Assembly Name** (ASSLY, Assy Name, etc.)
        - **Part Number** (PARTNO, Part No, etc.)
        - **Description** (DESCRIPTION, Part Description, etc.)
        
        ### 🔧 Optional Columns:
        - **Quantity per Vehicle** (QTY/VEH, Qty Bin, etc.)
        - **Type** (TYPE, Type name, etc.)
        - **Line Location** (LINE LOCATION, Line Location, etc.)
        - **Part Status** (PART STATUS, Status, etc.)
        - **Bin Type** (BIN TYPE, Container Type, etc.)
        
        ### ✨ Features:
        - 🏷️ Professional sticker layout (10cm x 15cm)
        - 📱 QR codes with complete part information
        - 🖼️ Custom logo support
        - 📍 Configurable line location boxes
        - 📄 High-quality PDF output
        - 🔍 Smart column detection
        """)

if __name__ == "__main__":
    main()

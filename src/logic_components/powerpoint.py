from logic_components.visuals import sensor_visual  # Re-import the function
from pptx import Presentation
import plotly.io as pio
import pandas as pd
from PIL import Image
from pptx.util import Inches
import os
import importlib
import logic_components.visuals  # Import the module
importlib.reload(logic_components.visuals)  # Reload the module


def make_powerpoint(df_visual, measure, folder_path_photo, folder_path_image, step_size_xaxis_days):

    max_neerslag = df_visual['neerslag'].max()
    max_sensorwaarde = df_visual[measure].max()
    img_path = None
    # Function to rotate an image and save it

    def rotate_image(image_path):
        image = Image.open(image_path)
        # Rotate 90 degrees to the right
        image = image.rotate(-180, expand=True)
        image.save(image_path)

    # Create a new PowerPoint presentation
    prs = Presentation()

    # Group the data by date and location
    grouped_visual = df_visual.groupby(["datum", "locatie"])[
        measure].mean().reset_index()

    # Modify the unique location list to account for combined locations
    unique_locations = list(grouped_visual["locatie"].unique())
    modified_locations = set([loc.split('_')[0] for loc in unique_locations])

    # Generate and save your plots as images
    for location_base in modified_locations:
        # Combine data for locations with suffixes _15 and _30
        combined_data = df_visual[df_visual['locatie'].str.startswith(
            location_base)]
        
        fig = sensor_visual(measure, combined_data,
                            max_neerslag, max_sensorwaarde, legend_top=True)

        # Adjust date for tick values
        unique_dates = pd.Series(df_visual['datum'].unique())
        unique_dates.sort_values(inplace=True)
        tick_dates = unique_dates.iloc[::step_size_xaxis_days]

        fig.update_xaxes(
            title_text="Datum",
            tickvals=tick_dates,
            ticktext=[date.strftime('%b-%d') for date in tick_dates]
        )

        # Update the fig layout before saving
        fig.update_layout(
            title=None, # This removes the title
            showlegend=False, # This hides the legend
            margin=dict(l=0, r=0, t=0, b=0), # This sets the margins
            plot_bgcolor='white', # This sets the plot background color
            paper_bgcolor='white', # This sets the overall background color of the figure
            xaxis=dict(
                showgrid=True, # Ensure gridlines are shown
                gridcolor='grey', # Set gridlines to grey
                linecolor='grey', # Set the x-axis line color to grey
                tickfont=dict(color='grey') # Set the color of the tick labels
            ),
            yaxis=dict(
                showgrid=True, # Ensure gridlines are shown
                gridcolor='grey', # Set gridlines to grey
                linecolor='grey', # Set the y-axis line color to grey
                tickfont=dict(color='grey') # Set the color of the tick labels
            )
        )

        plot_path = folder_path_image + f'{location_base}.png'
        pio.write_image(fig, plot_path)

    # Loop through modified locations
    for location_base in sorted(modified_locations):
        print(location_base)
        folder_path = folder_path_photo + location_base

        # List all files in the folder
        file_list = os.listdir(folder_path)

        file_found = False
        # Loop through each file in the folder
        for file_name in file_list:
            # Check if the path points to a file (not a subdirectory)
            if os.path.isfile(os.path.join(folder_path, file_name)):
                # Process the file
                if file_name[:3] == 'pp_':
                    img_path = folder_path + f'/{file_name}'
                    file_found = True
                    break

        if not file_found:
            print(f'no file found for location {location_base}')

        plot_path = folder_path_image + f'{location_base}.png'

        rotate_lst = []

        if img_path:
            if location_base in rotate_lst:
                rotate_image(img_path)

            # Create a new slide with a layout that has two content placeholders
            # You might need to change the index depending on your template
            slide_layout = prs.slide_layouts[1]
            slide = prs.slides.add_slide(slide_layout)

            # Add a title to the slide
            title_placeholder = slide.shapes.title
            title_placeholder.text = location_base

            # Add the photo to the left placeholder
            slide.shapes.add_picture(img_path, Inches(
                0), Inches(2), height=Inches(5))

            # Add the plot image to the right placeholder
            slide.shapes.add_picture(plot_path, Inches(
                3.8), Inches(2), height=Inches(4.4))
        else:
            print(f'No image path available for {location_base}')

    return prs

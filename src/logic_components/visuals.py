# import plotly.graph_objects as go
# from plotly.subplots import make_subplots
# import numpy as np


# def sensor_visual(measure, df_visual, max_neerslag, max_sensorwaarde, legend_top=False):

#     # Group the data by date and location
#     grouped_visual = df_visual.groupby(["datum", "locatie"])[
#         measure].mean().reset_index()

#     # Create a subplot with two y-axes
#     fig = make_subplots(specs=[[{"secondary_y": True}]])

#     # Add scatter traces for each location
#     for location in grouped_visual["locatie"].unique():
#         location_data = grouped_visual[grouped_visual["locatie"] == location]
#         fig.add_trace(
#             go.Scatter(
#                 x=location_data["datum"], y=location_data[measure],
#                 mode='markers+lines', marker=dict(size=4.5),
#                 name=f"Locatie {location}"),
#             secondary_y=False,
#         )

#         # Calculate the percentage difference
#         y_vals = location_data[measure].values
#         perc_diff = np.diff(y_vals) / y_vals[:-1] * 100  # numpy diff function calculates the difference between consecutive elements

#         # Add None to the beginning of the array to offset the x values
#         perc_diff = np.insert(perc_diff, 0, None)

#         # Add trace for percentage difference
#         fig.add_trace(
#             go.Scatter(
#                 x=location_data["datum"], y=perc_diff,
#                 mode='lines', line=dict(dash='dot'),
#                 name="Procent verandering"),
#             secondary_y=False,
#         )

#     # fig.add_trace(
#     #     go.Scatter(x=df_visual["datum"].unique(), y=df_visual.groupby("datum")["neerslag"].mean(), name="Neerslag", line=dict(color="black", width=2, dash='dash')),
#     #     secondary_y=True,
#     # )

#     # Add a line trace for precipitation
#     neerslag_data = df_visual.groupby("datum")["neerslag"].mean().reset_index()
#     fig.add_trace(
#         go.Scatter(x=neerslag_data["datum"], y=neerslag_data["neerslag"],
#                    mode='markers+lines',
#                    marker=dict(size=4.5),
#                    name="Neerslag",
#                    line=dict(color="black", width=2, dash='dash')),
#         secondary_y=True,
#     )

#     # Set the range for the secondary y-axis
#     fig.update_yaxes(range=[0, max_neerslag], secondary_y=True)
#     fig.update_yaxes(range=[0, max_sensorwaarde], secondary_y=False)

#     # Set the title and axis labels
#     fig.update_layout(
#         title_text=f"{measure} en neerslag per datum"
#     )
#     fig.update_xaxes(title_text="Datum")
#     fig.update_yaxes(title_text=f"{measure}", secondary_y=False)
#     fig.update_yaxes(title_text="Neerslag", secondary_y=True)

#     if legend_top:
#         fig.update_layout(
#             title=dict(
#                 y=0.98,  # Adjusts the vertical position of the title
#                 yanchor='bottom'  # Uses the bottom of the title text as the reference
#             ),
#             legend=dict(
#                 x=0.5,
#                 y=1.12,  # Adjusts the vertical position of the legend
#                 xanchor='center',
#                 yanchor='bottom'
#             ),
#             # yaxis=dict(
#             #     range=[0, 50]
#             # )
#         )

#     return fig

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np


def sensor_visual(measure, df_visual, max_neerslag, max_sensorwaarde, legend_top=False):

    grouped_visual = df_visual.groupby(["datum", "locatie"])[
        measure].mean().reset_index()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    for location in grouped_visual["locatie"].unique():
        location_data = grouped_visual[grouped_visual["locatie"] == location]
        fig.add_trace(
            go.Scatter(
                x=location_data["datum"], y=location_data[measure],
                mode='markers+lines', marker=dict(size=4.5),
                name=f"Locatie {location}"),
            secondary_y=False,
        )

    neerslag_data = df_visual.groupby("datum")["neerslag"].mean().reset_index()
    fig.add_trace(
        go.Scatter(x=neerslag_data["datum"], y=neerslag_data["neerslag"],
                   mode='markers+lines',
                   marker=dict(size=4.5),
                   name="Neerslag",
                   line=dict(color="black", width=2)),
        secondary_y=True,
    )

    fig.update_yaxes(range=[0, max_neerslag], secondary_y=True)
    fig.update_yaxes(range=[0, max_sensorwaarde], secondary_y=False)

    # Adjusting the layout for three y-axes
    fig.update_layout(
        yaxis=dict(
            domain=[0, 0.85]
        ),
        yaxis2=dict(
            domain=[0, 0.85],
            anchor="free",
            position=0.91
        )
    )

    fig.update_layout(
        title_text=f"{measure} en neerslag per datum"
    )
    fig.update_xaxes(title_text="Datum")
    fig.update_yaxes(title_text="Permittivity", secondary_y=False)
    fig.update_yaxes(title_text="Neerslag", secondary_y=True)

    if legend_top:
        fig.update_layout(
            title=dict(
                y=0.98,
                yanchor='bottom'
            ),
            legend=dict(
                x=0.5,
                y=1.12,
                xanchor='center',
                yanchor='bottom'
            ),
        )

    return fig
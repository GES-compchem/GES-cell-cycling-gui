from typing import Dict, List, Tuple, Union
import math, logging, sys, os, traceback, pickle
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from copy import deepcopy

from core.gui_core import (
    ProgramStatus,
    ExperimentSelector,
    SingleCycleSeries,
    StackedPlotSettings,
    ComparisonPlotSettings,
)
from core.experiment import Experiment
from core.utils import set_production_page_style, force_update_once
from core.colors import get_plotly_color, RGB_to_HEX
from echemsuite.cellcycling.cycles import HalfCycle


st.set_page_config(layout="wide")
set_production_page_style()

# Fetch logger from the session state
if "Logger" in st.session_state:
    logger: logging.Logger = st.session_state["Logger"]
else:
    st.error("**ERROR:** Please return to the file manager page to initialize session")
    raise RuntimeError("Logger not found in session state")

# %% Definition of labels and functions specific to the cycles plotting

HALFCYCLE_SERIES = [
    "time",
    "voltage",
    "current",
    "charge",
    "power",
    "energy",
]


def get_halfcycle_series(
    halfcycle: HalfCycle,
    title: str,
    volume: Union[None, float] = None,
    area: Union[None, float] = None,
) -> Tuple[str, pd.Series]:
    """
    Given the halfcycle of interest and the title of the data series, retuns the pandas
    Serier containing the data to plot

    Arguments
    ---------
        halfcycle : HalfCycle
            the halfcycle from which the data must be taken
        title : str
            the title of the series to be taken from the halfcycle. Note that the title
            must match one of the entries of the HALFCYCLE_SERIES list variable.
        volume: Union[None, float]
            if not None will trigger the normalization of current, charge and energy per unit area
        area: Union[None, float]
            if not None will trigger the normalization of current, charge and energy per unit area
    """
    if title == "time":
        return "Time (s)", halfcycle.time

    elif title == "voltage":
        return "Voltage (V)", halfcycle.voltage

    elif title == "current":
        current = halfcycle.current
        if area is None:
            return "Current (A)", current
        else:
            return "Current density (A/cm<sup>2</sup>)", current / area

    elif title == "charge":
        charge = halfcycle.Q
        if volume is None:
            return "Capacity (mAh)", charge
        else:
            return "Volumetric capacity (Ah/L)", charge / (1000 * volume)

    elif title == "power":
        power = halfcycle.power
        if area is None:
            return "Power (W)", power
        else:
            return "Power density (mW/cm<sup>2</sup>)", 1000 * power / area

    elif title == "energy":
        energy = halfcycle.energy
        if volume is None:
            return "Energy (mWh)", energy
        else:
            return "Energy density (Wh/L)", energy / (1000 * volume)

    else:
        raise ValueError


# Create an instance of the ExperimentSelector class to be used to define the data to plot
# and chache it in the session state
if "Page2_CyclePlotSelection" not in st.session_state:
    st.session_state["Page2_CyclePlotSelection"] = ExperimentSelector()
    st.session_state["Page2_ManualSelectorBuffer"] = []
    st.session_state["Page2_ComparisonPlot"] = []
    st.session_state["Page2_stacked_settings"] = StackedPlotSettings()
    st.session_state["Page2_comparison_settings"] = ComparisonPlotSettings()


def clean_manual_selection_buffer():
    st.session_state["Page2_ManualSelectorBuffer"] = []


def remove_experiment_from_series_buffer(name: str) -> None:
    """
    Removes all the entry related to a given experiment from the selection buffer of the
    comparison plot

    Arguments
    ---------
    name : str
        the name of the experiment to remove
    """
    selected_series: List[SingleCycleSeries] = st.session_state["Page2_ComparisonPlot"]
    buffer = deepcopy(selected_series)
    selected_series.clear()

    for series in buffer:
        if series.experiment_name != name:
            selected_series.append(series)


# Fetch a fresh instance of the Progam Status and Experiment Selection variables from the session state
status: ProgramStatus = st.session_state["ProgramStatus"]
selected_experiments: ExperimentSelector = st.session_state["Page2_CyclePlotSelection"]
selected_series: List[SingleCycleSeries] = st.session_state["Page2_ComparisonPlot"]
stacked_settings: StackedPlotSettings = st.session_state["Page2_stacked_settings"]
comparison_settings: ComparisonPlotSettings = st.session_state["Page2_comparison_settings"]

try:

    logger.info("RUNNING cycles plotter page rendering")

    # Check if the main page has set up the proper session state variables and check that at
    # least one experiment has been loaded
    enable = True
    if "ProgramStatus" not in st.session_state:
        enable = False
    else:
        status: ProgramStatus = st.session_state["ProgramStatus"]
        if len(status) == 0:
            enable = False

    with st.sidebar:
        st.info(f'Session token: {st.session_state["Token"]}')

    # Set the title of the page and print some generic instruction
    st.title("Cycles plotter")

    st.write(
        """In this page you can analyze cycling experiments comparing the profile associated to
        each charge/discharge cycle. The stacked plot tab will allow you to visualize, in 
        individual sub-plots, cycles belonging to different experiments. The comparison plot tab
        will allow you to generate a single plot in which cycles belonging to different 
        experiments can be overlayed and compared"""
    )

    # If there is one or more experiment loaded in the buffer start the plotter GUI
    if enable:

        stacked_plot, comparison_plot = st.tabs(["Stacked plot", "Comparison plot"])

        # Define the stacked plot tab to compare cycling of different experiments
        with stacked_plot:

            logger.info("Rendering stacked plot tab")

            st.markdown("### Experiments plotter")

            # Define a container to hold the experiment selection box
            with st.container():

                selection = None  # Experiment selected
                col1, col2 = st.columns([4, 1])

                # Create a selectbox from which the user can decide which experiment to analyze
                with col1:

                    # Take the available experiments as the names of the experiments loaded in the
                    # program status object removing the ones already selected
                    available_experiments = [
                        obj.name
                        for obj in status
                        if obj.name not in selected_experiments.names
                    ]
                    selection = st.selectbox(
                        "Select the experiment to be added to the view",
                        available_experiments,
                    )

                    logger.debug(f"-> Selected experiment: {selection}")

                # Show and add button to allow the user to add the selected experiment to the list
                with col2:
                    st.write("")  # Added for vertical spacing
                    st.write("")  # Added for vertical spacing
                    add = st.button("➕ Add", key="stacked")

                    if add:
                        logger.debug(f"-> PRESSED add button")

                    if add and selection is not None:
                        selected_experiments.set(
                            selection
                        )  # Set the experiment in the selector
                        logger.info(f"ADDED experiment {selection} to selection")
                        st.experimental_rerun()  # Rerun the page to update the selector box

            st.markdown("---")

            # If the Experiment selector is not empty show to the user the cycle selector interface
            if selected_experiments.is_empty == False:

                logger.info("Entering view selection/edit section")

                # Create an expander holding the Cycle selection options
                with st.expander("Cycle selector/editor", expanded=False):

                    col1, col2 = st.columns(2, gap="medium")

                    # Create a column in which the user can select the experiment to manipulate
                    with col1:
                        # Show a selectbox button to allow the selection of the wanted experiment
                        st.markdown("###### Loaded experiments selector")
                        current_view = st.selectbox(
                            "Select the experiment to edit",
                            selected_experiments.names,
                            on_change=clean_manual_selection_buffer,
                        )
                        logger.info(f"SELECTED experiment: {current_view}")

                        # Show a button to remove the selected experiment from the view
                        remove_current = st.button("➖ Remove from view")
                        if remove_current:
                            logger.info("REMOVED {current_view} from view")
                            index = selected_experiments.remove(current_view)
                            st.experimental_rerun()  # Rerun the page to update the GUI

                        st.markdown("---")

                        # Show a selector allowing the user to choose how to set the cycles view
                        st.markdown("###### Mode of operation")
                        view_mode = st.radio(
                            "Select the mode of operation",
                            [
                                "Constant-interval cycle selector",
                                "Manual cycle selector",
                                "Data series editor",
                            ],
                        )
                        logger.debug(f"-> Mode of operation {view_mode}")

                    # Create a column based on the selections made in the first one in which the
                    # user can select the desired cycles
                    with col2:

                        # Get the complete cycle list associated to the selected experiment
                        id = status.get_index_of(current_view)
                        cycles = status[id]._cycles

                        # Show the appropriate selection box
                        if (
                            view_mode == "Constant-interval cycle selector"
                            and len(cycles) > 1
                        ):

                            logger.info("ENTERING contant-interval view selection mode")

                            st.markdown("###### Constant interval cycle selector")

                            max_cycle = len(cycles) - 1

                            # Show a number input to allow the selection of the start point
                            start = st.number_input(
                                "Start",
                                min_value=0,
                                max_value=max_cycle - 1,
                                step=1,
                            )
                            start = int(start)
                            logger.debug(f"-> start: {start}")

                            # Show a number input to allow the selection of the stop point, please
                            # notice how the stop point is excluded from the interval and, as such,
                            # must be allowed to assume a maximum value equal to the last index +1
                            stop = st.number_input(
                                "Stop (included)",
                                min_value=start + 1,
                                max_value=max_cycle,
                                value=max_cycle,
                                step=1,
                            )
                            stop = int(stop)
                            logger.debug(f"-> stop: {stop}")

                            guess_stride = int(math.ceil(max_cycle / 10))
                            # Show a number input to allow the selection of the stride
                            stride = st.number_input(
                                "Stride",
                                min_value=1,
                                max_value=max_cycle,
                                step=1,
                                value=guess_stride,
                            )
                            stride = int(stride)
                            logger.debug(f"-> stride: {stride}")

                            apply = st.button("✅ Apply", key="stacked_stride_apply")
                            if apply:
                                logger.debug("-> Pressed apply button")
                                cycles_in_view = np.arange(start, stop + 1, step=stride)
                                selected_experiments.set(current_view, cycles_in_view)
                                logger.info(f"SET view using cycles {cycles_in_view}")

                        elif view_mode == "Constant-interval cycle selector":
                            st.info(
                                f"""`ADVICE ON MODE OF OPERATION: ` 
                                The selected experiment has only {len(cycles)} cycle.
                                Stride selection mode cannot be used in this instance. Please 
                                select the *"Manual selector"* option in the *"Selector mode menu"*."""
                            )

                        elif view_mode == "Manual cycle selector":

                            logger.info("ENTERING manual view selection mode")

                            st.markdown("###### Manual cycle selector")

                            # Give a easy name to the temporary selection buffer
                            manual_selection_buffer = st.session_state[
                                "Page2_ManualSelectorBuffer"
                            ]

                            # When empty, fill the temorary selection buffer with the selected
                            # experiment object content
                            if manual_selection_buffer == []:
                                manual_selection_buffer = selected_experiments[current_view]
                            logger.debug(
                                f"-> Temporary selection buffer: {manual_selection_buffer}"
                            )

                            # Show a multiple selection box with all the available cycles in which
                            # the user can manually add or remove a cycle, save the new list in a
                            # temporary buffer used on the proper rerun
                            buffer_selection = st.multiselect(
                                "Select the cycles",
                                [obj.number for obj in cycles],
                                default=manual_selection_buffer,
                            )
                            buffer_selection.sort()  # Sort the traces automatically
                            st.session_state[
                                "Page2_ManualSelectorBuffer"
                            ] = buffer_selection
                            logger.debug(f"-> Selection buffer: {buffer_selection}")

                            # If the temporary buffer is found to be different from the one currently
                            # set for the current view, update the current view
                            if buffer_selection != selected_experiments[current_view]:
                                logger.info(f"SET view using cycles {buffer_selection}")
                                selected_experiments.set(
                                    current_view,
                                    cycles=buffer_selection,
                                )
                                st.experimental_rerun()

                            # Print a remove all button to allow the user to remove alle the selected cycles
                            clear_current_view = st.button("🧹 Clear All")
                            if clear_current_view:
                                logger.info("Cleared selection buffer")
                                selected_experiments.empty_view(current_view)
                                clean_manual_selection_buffer()
                                st.experimental_rerun()  # Rerun to update the GUI

                        else:

                            logger.info("ENTERING view edit mode")

                            st.markdown("###### Data series editor")

                            # Reset all labels given to the series
                            reset = st.button("🧹 Reset all names")
                            if reset:
                                logger.info("RESET all labels to the default values")
                                selected_experiments.reset_default_labels(current_view)

                            # Let the user select the series and its new name
                            selected_series_to_edit = st.selectbox(
                                "Select the cycle series to edit",
                                selected_experiments[current_view],
                            )
                            logger.debug(
                                f"-> Cycle series to edit {selected_series_to_edit}"
                            )

                            current_label = selected_experiments.get_label(
                                current_view, selected_series_to_edit
                            )
                            new_label = st.text_input(
                                "Select the new label for the series", value=current_label
                            )
                            logger.debug(
                                f"-> New label value for the series {selected_series_to_edit}"
                            )

                            apply = st.button("✅ Apply")
                            if apply and new_label != "":
                                logger.info(
                                    f"Applyed label {new_label} to series {selected_series_to_edit}"
                                )
                                selected_experiments.set_cycle_label(
                                    current_view, selected_series_to_edit, new_label
                                )

            # If there are selected experiment in the buffer start the plot operations
            if not selected_experiments.is_empty:

                logger.info("Entering plot section")

                col1, col2 = st.columns([4, 1])

                # Visualize some plot options in a small coulomn on the right
                with col2:

                    logger.info("Entering plot option section")

                    st.markdown("#### Plot options")

                    with st.expander("Axis options:"):
                        st.markdown("###### Axis")
                        stacked_settings.x_axis = st.selectbox(
                            "Select the series x axis",
                            HALFCYCLE_SERIES,
                            index=HALFCYCLE_SERIES.index(stacked_settings.x_axis)
                            if stacked_settings.x_axis
                            else 0,
                        )
                        logger.debug(f"-> X axis: {stacked_settings.x_axis}")

                        sub_HALFCYCLE_SERIES = [
                            x for x in HALFCYCLE_SERIES if x != stacked_settings.x_axis
                        ]
                        stacked_settings.y_axis = st.selectbox(
                            "Select the series y axis",
                            sub_HALFCYCLE_SERIES,
                            index=sub_HALFCYCLE_SERIES.index(stacked_settings.y_axis)
                            if stacked_settings.y_axis
                            and stacked_settings.y_axis in sub_HALFCYCLE_SERIES
                            else 0,
                        )
                        logger.debug(f"-> Y axis: {stacked_settings.y_axis}")

                        stacked_settings.shared_x = st.checkbox(
                            "Use shared x-axis",
                            value=stacked_settings.shared_x
                            if stacked_settings.shared_x and len(selected_experiments) == 1
                            else False,
                            disabled=True if len(selected_experiments) == 1 else False,
                        )
                        logger.debug(f"-> Shared X mode: {stacked_settings.shared_x}")

                        volume_is_available = True
                        for name in selected_experiments.view.keys():
                            experiment_id = status.get_index_of(name)
                            experiment = status[experiment_id]
                            if experiment.volume is None:
                                volume_is_available = False
                                break

                        stacked_settings.scale_by_volume = st.checkbox(
                            "Scale values by volume",
                            value=stacked_settings.scale_by_volume
                            if volume_is_available
                            else False,
                            disabled=not volume_is_available,
                        )
                        logger.debug(
                            f"-> Scale by volume: {stacked_settings.scale_by_volume}"
                        )

                        area_is_available = True
                        for name in selected_experiments.view.keys():
                            experiment_id = status.get_index_of(name)
                            experiment = status[experiment_id]
                            if experiment.area is None:
                                area_is_available = False
                                break

                        stacked_settings.scale_by_area = st.checkbox(
                            "Scale values by area",
                            value=stacked_settings.scale_by_area
                            if area_is_available
                            else False,
                            disabled=not area_is_available,
                        )
                        logger.debug(f"-> Scale by area: {stacked_settings.scale_by_area}")

                    with st.expander("Series options:"):
                        st.markdown("###### Series")
                        stacked_settings.show_charge = st.checkbox(
                            "Show charge", value=stacked_settings.show_charge
                        )
                        logger.debug(f"-> Show charge: {stacked_settings.show_charge}")

                        stacked_settings.show_discharge = st.checkbox(
                            "Show discharge", value=stacked_settings.show_discharge
                        )
                        logger.debug(
                            f"-> Show discharge: {stacked_settings.show_discharge}"
                        )

                    with st.expander("Aspect options:"):
                        st.markdown("###### Aspect")

                        stacked_settings.reverse = st.checkbox(
                            "Reversed colorscale",
                            value=stacked_settings.reverse,
                            key="stacked_reverse",
                        )
                        logger.debug(f"-> Reversed colorscale: {stacked_settings.reverse}")

                        stacked_settings.font_size = int(
                            st.number_input(
                                "Label/tick font size",
                                min_value=4,
                                value=stacked_settings.font_size,
                            )
                        )
                        logger.debug(
                            f"-> Label/tick font size: {stacked_settings.font_size}"
                        )

                        stacked_settings.axis_font_size = int(
                            st.number_input(
                                "Axis title font size",
                                min_value=4,
                                value=stacked_settings.axis_font_size,
                            )
                        )
                        logger.debug(
                            f"-> Axis font size: {stacked_settings.axis_font_size}"
                        )

                        stacked_settings.plot_height = int(
                            st.number_input(
                                "Subplot height",
                                min_value=10,
                                value=stacked_settings.plot_height,
                                step=10,
                            )
                        )
                        logger.debug(f"-> Plot height: {stacked_settings.plot_height}")

                with col1:

                    logger.info("Entering plot rendering section")

                    # Create a figure with a number of subplots equal to the numebr of selected experiments
                    fig = make_subplots(
                        cols=1,
                        rows=len(selected_experiments),
                        shared_xaxes=stacked_settings.shared_x,
                        vertical_spacing=0 if stacked_settings.shared_x else None,
                    )

                    x_label, y_label = None, None

                    # For eache experiment update the correspondent subplot
                    for index, name in enumerate(selected_experiments.names):

                        logger.debug(f"-> Plotting data for experiment {name}")

                        # Get the cycle list from the experiment
                        exp_id = status.get_index_of(name)
                        experiment: Experiment = status[exp_id]
                        cycles = experiment._cycles
                        volume = (
                            experiment.volume if stacked_settings.scale_by_volume else None
                        )
                        area = experiment.area if stacked_settings.scale_by_area else None

                        # Get the user selected cycles and plot only the corresponden lines
                        num_traces = len(selected_experiments[name])
                        logger.debug(f"-> Number of traces: {num_traces}")

                        for trace_id, cycle_id in enumerate(selected_experiments[name]):

                            # Get the shade associated to the current trace
                            shade = RGB_to_HEX(
                                *experiment.color.get_shade(
                                    trace_id, num_traces, reversed=stacked_settings.reverse
                                )
                            )

                            # extract the cycle given the id selected
                            cycle = cycles[cycle_id]

                            # Print the charge halfcycle
                            if (
                                cycle.charge is not None
                                and stacked_settings.show_charge is True
                            ):

                                series_name = selected_experiments.get_label(name, cycle_id)

                                x_label, x_series = get_halfcycle_series(
                                    cycle.charge, stacked_settings.x_axis, volume, area
                                )
                                y_label, y_series = get_halfcycle_series(
                                    cycle.charge, stacked_settings.y_axis, volume, area
                                )

                                fig.add_trace(
                                    go.Scatter(
                                        x=x_series,
                                        y=y_series,
                                        line=dict(color=shade),
                                        name=series_name,
                                        mode="lines",
                                    ),
                                    row=index + 1,
                                    col=1,
                                )

                            # Print the discharge halfcycle
                            if (
                                cycle.discharge is not None
                                and stacked_settings.show_discharge is True
                            ):

                                series_name = selected_experiments.get_label(name, cycle_id)

                                x_label, x_series = get_halfcycle_series(
                                    cycle.discharge, stacked_settings.x_axis, volume, area
                                )
                                y_label, y_series = get_halfcycle_series(
                                    cycle.discharge, stacked_settings.y_axis, volume, area
                                )

                                fig.add_trace(
                                    go.Scatter(
                                        x=x_series,
                                        y=y_series,
                                        line=dict(color=shade),
                                        name=series_name,
                                        showlegend=False if cycle.charge else True,
                                        mode="lines",
                                    ),
                                    row=index + 1,
                                    col=1,
                                )

                    if x_label and y_label:

                        # Update the settings of the x-axis
                        fig.update_xaxes(
                            title_text=x_label,
                            showline=True,
                            linecolor="black",
                            gridwidth=1,
                            gridcolor="#DDDDDD",
                            title_font={"size": stacked_settings.axis_font_size},
                            range=stacked_settings.x_range,
                            dtick=stacked_settings.x_dtick,
                        )

                        if stacked_settings.shared_x:
                            for n in range(len(selected_experiments)):
                                fig.update_xaxes(title_text="", row=n, col=1)

                        # Update the settings of the y-axis
                        fig.update_yaxes(
                            title_text=y_label,
                            showline=True,
                            linecolor="black",
                            gridwidth=1,
                            gridcolor="#DDDDDD",
                            title_font={"size": stacked_settings.axis_font_size},
                            range=stacked_settings.y_range,
                            dtick=stacked_settings.y_dtick,
                        )

                        # Update the settings of plot layout
                        fig.update_layout(
                            plot_bgcolor="#FFFFFF",
                            height=stacked_settings.plot_height
                            * len(selected_experiments.names),
                            width=None,
                            font=dict(size=stacked_settings.font_size),
                        )

                        st.plotly_chart(fig, use_container_width=True, theme=None)

                with col2:

                    logger.info("Re-Entering plot option section to render export section")

                    # Define a expander to hold the options relative to the plot range and ticks
                    with st.expander("Range/ticks options"):
                        st.markdown("###### Range options")

                        # Show a checkbox to enable/disable automatic axis range
                        st.markdown("X-axis range")
                        x_autorange = st.checkbox(
                            "Use automatic range for X", value=stacked_settings.x_autorange
                        )
                        logger.debug(f"-> X Autorange: {x_autorange}")

                        if x_autorange != stacked_settings.x_autorange:
                            stacked_settings.x_autorange = x_autorange
                            stacked_settings.x_range = None
                            logger.info(f"X Autorange: {stacked_settings.x_autorange}")
                            st.experimental_rerun()

                        # If autorange is set to false and no range is available get the
                        # starting values for the range according to the automatic ones
                        if (
                            stacked_settings.x_autorange is False
                            and stacked_settings.x_range is None
                        ):
                            figure_data = fig.full_figure_for_development(warn=False)
                            xmin, xmax = None, None
                            for i in range(0, len(selected_experiments)):
                                label = "xaxis" if i == 0 else f"xaxis{i+1}"
                                xrange = [float(x) for x in figure_data.layout[label].range]
                                xmin = xrange[0] if xmin is None else min(xmin, xrange[0])
                                xmax = xrange[1] if xmax is None else max(xmax, xrange[1])
                            stacked_settings.x_range = [float(xmin), float(xmax)]
                            logger.info(f"SET x range: {stacked_settings.x_range}")

                        # If the autorange is false get the user input about the desired range
                        # and save it in the sesison state
                        if stacked_settings.x_autorange is False:

                            xmin, xmax = stacked_settings.x_range
                            xmin = float(st.number_input("X-min", value=xmin, step=0.01))
                            xmax = float(st.number_input("X-max", value=xmax, step=0.01))
                            xrange = [xmin, xmax]

                            if xrange != stacked_settings.x_range:
                                stacked_settings.x_range = xrange
                                logger.info(f"SET x range: {stacked_settings.x_range}")
                                st.experimental_rerun()

                        # If the autorange is false deactivate custom ticks
                        else:
                            stacked_settings.custom_x_dticks = False

                        # Show a checkbox to enable custom axis tick
                        stacked_settings.custom_x_dticks = st.checkbox(
                            "Use custom X ticks intervals",
                            value=stacked_settings.custom_x_dticks,
                            disabled=stacked_settings.x_autorange,
                        )
                        logger.info(
                            f"Use custom X ticks: {stacked_settings.custom_x_dticks}"
                        )

                        # If the custom tick option is enable get user input
                        if stacked_settings.custom_x_dticks:

                            # If no default value is set, compute one based on the range
                            if stacked_settings.x_dtick is None:
                                x_range = stacked_settings.x_range
                                stacked_settings.x_dtick = float(
                                    (x_range[1] - x_range[0]) / 10.0
                                )
                                logger.debug(
                                    f"-> Setting X dtick default: {stacked_settings.x_dtick}"
                                )

                            # Get user input
                            stacked_settings.x_dtick = float(
                                st.number_input(
                                    "X tick interval",
                                    value=stacked_settings.x_dtick,
                                    step=1e-3,
                                )
                            )
                            logger.info(f"SET X dtick: {stacked_settings.x_dtick}")

                        # If custom x dtick option is false celar the selected dtick value
                        elif stacked_settings.x_dtick is not None:
                            stacked_settings.x_dtick = None

                        st.markdown("Y-axis range")

                        # Show a checkbox to enable/disable automatic axis range
                        y_autorange = st.checkbox(
                            "Use automatic range for Y", value=stacked_settings.y_autorange
                        )
                        logger.debug(f"-> Y Autorange: {y_autorange}")

                        if y_autorange != stacked_settings.y_autorange:
                            stacked_settings.y_autorange = y_autorange
                            stacked_settings.y_range = None
                            logger.info(f"Y Autorange: {stacked_settings.y_autorange}")
                            st.experimental_rerun()

                        # If autorange is set to false and no range is available get the
                        # starting values for the range according to the automatic ones
                        if (
                            stacked_settings.y_autorange is False
                            and stacked_settings.y_range is None
                        ):

                            figure_data = fig.full_figure_for_development(warn=False)

                            ymin, ymax = None, None
                            for i in range(len(selected_experiments)):
                                label = "yaxis" if i == 0 else f"yaxis{i+1}"
                                yrange = [float(y) for y in figure_data.layout[label].range]
                                ymin = yrange[0] if ymin is None else min(ymin, yrange[0])
                                ymax = yrange[1] if ymax is None else max(ymax, yrange[1])
                            stacked_settings.y_range = [float(ymin), float(ymax)]

                        # If the autorange is false get the user input about the desired range
                        # and save it in the sesison state
                        if stacked_settings.y_autorange is False:

                            ymin, ymax = stacked_settings.y_range
                            ymin = float(st.number_input("Y-min", value=ymin, step=0.01))
                            ymax = float(st.number_input("Y-max", value=ymax, step=0.01))
                            yrange = [ymin, ymax]

                            if yrange != stacked_settings.y_range:
                                stacked_settings.y_range = yrange
                                logger.info(f"Y range set to: {stacked_settings.y_range}")
                                st.experimental_rerun()

                        # If the autorange is false deactivate custom ticks
                        else:
                            stacked_settings.custom_y_dticks = False

                        # Show a checkbox to enable custom axis tick
                        stacked_settings.custom_y_dticks = st.checkbox(
                            "Use custom Y ticks intervals",
                            value=stacked_settings.custom_y_dticks,
                            disabled=stacked_settings.y_autorange,
                        )
                        logger.info(
                            f"Use custom Y ticks: {stacked_settings.custom_y_dticks}"
                        )

                        # If the custom tick option is enable get user input
                        if stacked_settings.custom_y_dticks:

                            # If no default value is set, compute one based on the range
                            if stacked_settings.y_dtick is None:
                                y_range = stacked_settings.y_range
                                stacked_settings.y_dtick = float(
                                    (y_range[1] - y_range[0]) / 5
                                )

                            # Get user input
                            stacked_settings.y_dtick = float(
                                st.number_input(
                                    "Y tick interval",
                                    value=stacked_settings.y_dtick,
                                    step=1e-3,
                                )
                            )
                            logger.info(f"SET Y dtick: {stacked_settings.x_dtick}")

                        # If custom y dtick option is false celar the selected dtick value
                        elif stacked_settings.y_dtick is not None:
                            stacked_settings.y_dtick = None

                    with st.expander("Export options:"):
                        st.markdown("###### Export")
                        available_formats = ["png", "jpeg", "svg", "pdf"]
                        stacked_settings.format = st.selectbox(
                            "Select the format of the file",
                            available_formats,
                            index=available_formats.index(stacked_settings.format)
                            if stacked_settings.format
                            else 0,
                        )
                        logger.debug(f"-> Export format: {stacked_settings.format}")

                        suggested_width = int(2.5 * stacked_settings.plot_height)
                        stacked_settings.total_width = int(
                            st.number_input(
                                "Total width",
                                min_value=10,
                                value=stacked_settings.total_width
                                if stacked_settings.total_width
                                else suggested_width,
                            )
                        )
                        logger.debug(f"-> Export width: {stacked_settings.total_width}")

                        # Set new layout options to account for the user selected width
                        fig.update_layout(
                            plot_bgcolor="#FFFFFF",
                            height=stacked_settings.plot_height
                            * len(selected_experiments.names),
                            width=stacked_settings.total_width,
                            font=dict(size=stacked_settings.font_size),
                        )

                        st.download_button(
                            "Download plot",
                            data=fig.to_image(format=stacked_settings.format),
                            file_name=f"cycle_plot.{stacked_settings.format}",
                            on_click=lambda msg: logger.info(msg),
                            args=[f"DOWNLOAD cycle_plot.{stacked_settings.format}"],
                            disabled=True
                            if not stacked_settings.show_charge
                            and not stacked_settings.show_discharge
                            else False,
                        )

        # Define a comparison plot tab to compare cycle belonging to different experiments
        with comparison_plot:

            logger.info("Rendering comparison plot tab")

            # Create a manager section allowing the user to select the trace to plot based on
            # the experiment name and the cycle number or using a stride base selection
            with st.expander("Series editor"):

                st.markdown("### Experiment selector")

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("##### Source experiment")
                    experiment_name = st.selectbox(
                        "Select the experiment",
                        status.get_experiment_names(),
                    )
                    exp_idx = status.get_index_of(experiment_name)
                    experiment = status[exp_idx]
                    cycle_numbers = [obj.number for obj in experiment._cycles]

                    logger.debug(f"-> Selected experiment: {experiment_name}")

                    use_base_color = st.checkbox("Use experiment base color", value=True)
                    logger.debug(f"-> Using basecolor from experiment: {use_base_color}")

                    clear_experiment = st.button(
                        "🧹 Remove from plot", key="Experiment_series_remove"
                    )

                    st.markdown("##### Selector mode")
                    selector_mode = st.radio(
                        "Select the cycle selector mode",
                        ["Stride based selector", "Manual selector", "Series editor"],
                    )

                    if clear_experiment:
                        logger.info(
                            f"REMOVING experiment {experiment_name} from selection buffer"
                        )
                        remove_experiment_from_series_buffer(experiment_name)
                        st.experimental_rerun()

                with col2:
                    if selector_mode == "Stride based selector" and len(cycle_numbers) > 1:

                        logger.info("Entering stride bases selection mode")
                        st.markdown("##### Stride-based cycle selector")

                        max_cycle = len(cycle_numbers) - 1

                        label_prefix = st.text_input(
                            "Select a label prefix for the selected series",
                            value=experiment_name,
                        )
                        logger.debug(f"-> Selected label prefix: {label_prefix}")

                        # Show a number input to allow the selection of the start point
                        start = st.number_input(
                            "Start",
                            min_value=0,
                            max_value=max_cycle - 1,
                            step=1,
                            key="comparison_start",
                        )
                        start = int(start)
                        logger.debug(f"-> start: {start}")

                        # Show a number input to allow the selection of the stop point, please
                        # notice how the stop point is excluded from the interval and, as such,
                        # must be allowed to assume a maximum value equal to the last index +1
                        stop = st.number_input(
                            "Stop (included)",
                            min_value=start + 1,
                            max_value=max_cycle,
                            value=max_cycle,
                            step=1,
                            key="comparison_stop",
                        )
                        stop = int(stop)
                        logger.debug(f"-> stop: {stop}")

                        guess_stride = int(math.ceil(max_cycle / 10))
                        # Show a number input to allow the selection of the stride
                        stride = st.number_input(
                            "Stride",
                            min_value=1,
                            max_value=max_cycle,
                            step=1,
                            value=guess_stride,
                            key="comparison_stride",
                        )
                        stride = int(stride)
                        logger.debug(f"-> stride: {stride}")

                        apply = st.button("✅ Apply", key="comparison_stride_apply")

                        if apply:
                            logger.debug("-> Pressed apply button")

                            remove_experiment_from_series_buffer(experiment_name)

                            cycles_in_selection = np.arange(start, stop + 1, step=stride)
                            for n in cycles_in_selection:
                                cycle = experiment._cycles[cycle_numbers.index(n)]

                                duplicate = False
                                for series in selected_series:
                                    if (
                                        series.experiment_name == experiment_name
                                        and series.cycle_id == n
                                    ):
                                        duplicate = True
                                        break
                                if duplicate:
                                    continue

                                selected_series.append(
                                    SingleCycleSeries(
                                        f"{label_prefix} [{n}]",
                                        experiment_name,
                                        n,
                                        hex_color=get_plotly_color(len(selected_series)),
                                        color_from_base=use_base_color,
                                    )
                                )
                            # logger.info(f"Selection buffer set to: {selected_series}")
                            st.experimental_rerun()

                    elif selector_mode == "Stride based selector":
                        st.info(
                            f"""`ADVICE ON MODE OF OPERATION: ` 
                            The selected experiment has only {len(cycle_numbers)} cycle.
                            Stride selection mode cannot be used in this instance. Please 
                            select the *"Manual selector"* option in the *"Selector mode menu"*."""
                        )

                    elif selector_mode == "Manual selector":
                        logger.info("Entering manual selection mode")
                        st.markdown("##### Manual cycle selector")

                        multiple = st.checkbox("Use multiple selection", value=True)
                        logger.debug(f"-> Multiple selector set to: {multiple}")

                        exclude = [
                            entry.cycle_id
                            for entry in selected_series
                            if entry.experiment_name == experiment_name
                        ]

                        selected_cycles = {}
                        if multiple:
                            logger.info("Entering multiple cycle selector")
                            cycle_numbers = st.multiselect(
                                "Select the cycle",
                                [n for n in cycle_numbers if n not in exclude],
                            )
                            logger.debug(f"-> Selected cycles: {cycle_numbers}")

                            label_prefix = st.text_input(
                                "Select a label prefix for the selected series",
                                value=experiment_name,
                            )
                            logger.debug(f"-> Selected label prefix: {label_prefix}")

                            for n in cycle_numbers:
                                selected_cycles[f"{label_prefix} [{n}]"] = n

                        else:
                            logger.info("Entering single cycle selector")
                            cycle_number = st.selectbox(
                                "Select the cycle",
                                [n for n in cycle_numbers if n not in exclude],
                            )
                            logger.debug(f"-> Selected cycle: {cycle_number}")

                            cycle_label = st.text_input(
                                "Select a label for the selected series",
                                value=f"{experiment_name} [{cycle_number}]",
                            )
                            logger.debug(f"-> Selected label: {cycle_label}")
                            selected_cycles[cycle_label] = cycle_number

                        add = st.button("➕ Add", key="comparison")

                        if add:
                            for label, n in selected_cycles.items():

                                logger.info(
                                    f"ADD cycle {n} from experiment {experiment_name} to comparison plot"
                                )

                                cycle = experiment._cycles[cycle_numbers.index(n)]
                                selected_series.append(
                                    SingleCycleSeries(
                                        label,
                                        experiment_name,
                                        n,
                                        hex_color=get_plotly_color(len(selected_series)),
                                        color_from_base=use_base_color,
                                    )
                                )

                            st.experimental_rerun()

                    elif selector_mode == "Series editor":

                        logger.info("Entering series option menu")
                        st.markdown("##### Series editor")

                        if selected_series != []:
                            logger.debug(f"-> {len(selected_series)} series found")

                            available_labels = [entry.label for entry in selected_series]

                            series_label = st.selectbox(
                                "Select series to edit", available_labels
                            )
                            logger.debug(f"-> Selected series to edit {series_label}")

                            series_position = available_labels.index(series_label)
                            current_series = selected_series[series_position]

                            st.write(f"Experiment name: `{current_series.experiment_name}`")
                            st.write(f"Cycle number: `{current_series.cycle_id}`")

                            remove = st.button(
                                "🧹 Remove from plot", key="Single_series_remove"
                            )
                            if remove:
                                logger.info(f"REMOVED series {series_label} form selection")
                                del selected_series[series_position]
                                st.experimental_rerun()

                            logger.info("Entering series edit menu")
                            st.markdown("##### Options:")

                            new_label = st.text_input(
                                "Select the series name", value=series_label
                            )
                            logger.debug(f"-> New label name: {new_label}")

                            override_color = st.checkbox(
                                "Override base color",
                                value=False if current_series.color_from_base else True,
                                disabled=False if current_series.color_from_base else True,
                            )

                            new_color = st.color_picker(
                                "Select the series color",
                                value=current_series.hex_color,
                                disabled=False if override_color else True,
                            )
                            logger.debug(f"-> New color name: {new_label}")

                            apply = st.button("✅ Apply", key="Apply_coparison_plot")
                            if apply:
                                logger.info(
                                    f"SET name {new_label} and color {new_color} to series {series_label}"
                                )
                                current_series.label = new_label
                                current_series.hex_color = new_color
                                if override_color:
                                    current_series.color_from_base = False
                                st.experimental_rerun()

                        else:
                            logger.debug(f"-> No series found")
                            st.warning("No series loaded to edit")

                    else:
                        raise RuntimeError

            logger.info(f"Currently selected series: {selected_series}")

            # Enter the plot section
            if selected_series != []:

                col1, col2 = st.columns([4, 1])

                # Create a small column on the right to allow the user to set some properties of
                # the plot
                with col2:

                    logger.info("Entering plot option section")

                    st.markdown("#### Plot options")

                    with st.expander("Axis options:"):
                        st.markdown("###### Axis")
                        comparison_settings.x_axis = st.selectbox(
                            "Select the series x axis",
                            HALFCYCLE_SERIES,
                            key="x_comparison",
                            index=HALFCYCLE_SERIES.index(comparison_settings.x_axis)
                            if comparison_settings.x_axis
                            else 0,
                        )
                        logger.debug(f"-> X axis: {comparison_settings.x_axis}")

                        sub_HALFCYCLE_SERIES = [
                            element
                            for element in HALFCYCLE_SERIES
                            if element != comparison_settings.x_axis
                        ]
                        comparison_settings.y_axis = st.selectbox(
                            "Select the series y axis",
                            sub_HALFCYCLE_SERIES,
                            index=sub_HALFCYCLE_SERIES.index(comparison_settings.y_axis)
                            if comparison_settings.y_axis
                            and comparison_settings.y_axis in sub_HALFCYCLE_SERIES
                            else 0,
                            key="y_comparison",
                        )
                        logger.debug(f"-> Y axis: {comparison_settings.y_axis}")

                        volume_is_available = True
                        for series in selected_series:
                            experiment_id = status.get_index_of(series.experiment_name)
                            experiment = status[experiment_id]
                            if experiment.volume is None:
                                volume_is_available = False
                                break

                        comparison_settings.scale_by_volume = st.checkbox(
                            "Scale values by volume",
                            value=comparison_settings.scale_by_volume
                            if volume_is_available
                            else False,
                            disabled=not volume_is_available,
                            key="comparison_plot",
                        )
                        logger.debug(
                            f"-> Scale by volume: {comparison_settings.scale_by_volume}"
                        )

                        area_is_available = True
                        for series in selected_series:
                            experiment_id = status.get_index_of(series.experiment_name)
                            experiment = status[experiment_id]
                            if experiment.area is None:
                                area_is_available = False
                                break

                        comparison_settings.scale_by_area = st.checkbox(
                            "Scale values by area",
                            value=comparison_settings.scale_by_area
                            if area_is_available
                            else False,
                            disabled=not area_is_available,
                            key="by_area_comparison",
                        )
                        logger.debug(
                            f"-> Scale by area: {comparison_settings.scale_by_area}"
                        )

                    with st.expander("Plot aspect options:"):
                        st.markdown("###### Aspect")
                        comparison_settings.font_size = int(
                            st.number_input(
                                "Label/tick font size",
                                min_value=4,
                                value=comparison_settings.font_size,
                                key="font_size_comparison",
                            )
                        )
                        logger.debug(
                            f"-> Label/tick font size: {comparison_settings.font_size}"
                        )

                        comparison_settings.axis_font_size = int(
                            st.number_input(
                                "Axis title font size",
                                min_value=4,
                                value=comparison_settings.axis_font_size,
                                key="axis_font_size_comparison",
                            )
                        )
                        logger.debug(
                            f"-> Axis title font size: {comparison_settings.axis_font_size}"
                        )

                        comparison_settings.reverse = st.checkbox(
                            "Use reversed experiment-based colorscale",
                            value=comparison_settings.reverse,
                        )
                        logger.debug(
                            f"-> Reversed colorscale: {comparison_settings.reverse}"
                        )

                        comparison_settings.height = int(
                            st.number_input(
                                "Plot height",
                                min_value=10,
                                value=comparison_settings.height
                                if comparison_settings.height
                                else 800,
                                step=10,
                            )
                        )
                        logger.debug(f"-> Plot height: {comparison_settings.height}")

                with col1:

                    logger.info("Entering plot rendering section")

                    # Create a figure with a single plo
                    fig = make_subplots(cols=1, rows=1)

                    # Generate a list of all the currently loaded series associated to a given
                    # experiment in order to calculate the shadow of color to be used when the
                    # color_from_base option is selected
                    experiment_based_selection: Dict[str, List[int]] = {}
                    for entry in selected_series:
                        exp_name = entry.experiment_name
                        if exp_name not in experiment_based_selection:
                            experiment_based_selection[exp_name] = [entry.cycle_id]
                        else:
                            experiment_based_selection[exp_name].append(entry.cycle_id)

                    # For each selected series add an independent trace to the plot
                    for entry in selected_series:

                        logger.debug(f"-> Plotting data for series {entry.label}")

                        name = entry.experiment_name
                        cycle_id = entry.cycle_id

                        exp_idx = status.get_index_of(name)
                        experiment = status[exp_idx]
                        cycle = experiment._cycles[cycle_id]

                        label = entry.label

                        # Compute the shade associated to the cycle of a given experiment
                        trace_id = experiment_based_selection[name].index(cycle_id)
                        num_traces = len(experiment_based_selection[name])
                        shade = RGB_to_HEX(
                            *experiment.color.get_shade(
                                trace_id, num_traces, reversed=comparison_settings.reverse
                            )
                        )
                        color = entry.hex_color if entry.color_from_base is False else shade

                        volume = (
                            status[exp_idx].volume
                            if comparison_settings.scale_by_volume
                            else None
                        )
                        area = (
                            status[exp_idx].area
                            if comparison_settings.scale_by_area
                            else None
                        )

                        # Print the charge halfcycle
                        if cycle.charge is not None:

                            x_label, x_series = get_halfcycle_series(
                                cycle.charge, comparison_settings.x_axis, volume, area
                            )
                            y_label, y_series = get_halfcycle_series(
                                cycle.charge, comparison_settings.y_axis, volume, area
                            )

                            fig.add_trace(
                                go.Scatter(
                                    x=x_series,
                                    y=y_series,
                                    line=dict(color=color),
                                    name=label,
                                    mode="lines",
                                ),
                                row=1,
                                col=1,
                            )

                        # Print the discharge halfcycle
                        if cycle.discharge is not None:

                            x_label, x_series = get_halfcycle_series(
                                cycle.discharge, comparison_settings.x_axis, volume, area
                            )
                            y_label, y_series = get_halfcycle_series(
                                cycle.discharge, comparison_settings.y_axis, volume, area
                            )

                            fig.add_trace(
                                go.Scatter(
                                    x=x_series,
                                    y=y_series,
                                    line=dict(color=color),
                                    name=label,
                                    showlegend=False if cycle.charge else True,
                                    mode="lines",
                                ),
                                row=1,
                                col=1,
                            )

                    # Update the settings of the x-axis
                    fig.update_xaxes(
                        title_text=x_label,
                        showline=True,
                        linecolor="black",
                        gridwidth=1,
                        gridcolor="#DDDDDD",
                        title_font={"size": comparison_settings.axis_font_size},
                    )

                    # Update the settings of the y-axis
                    fig.update_yaxes(
                        title_text=y_label,
                        showline=True,
                        linecolor="black",
                        gridwidth=1,
                        gridcolor="#DDDDDD",
                        title_font={"size": comparison_settings.axis_font_size},
                    )

                    # Update the settings of plot layout
                    fig.update_layout(
                        plot_bgcolor="#FFFFFF",
                        height=comparison_settings.height,
                        width=None,
                        font=dict(size=comparison_settings.font_size),
                    )

                    st.plotly_chart(fig, use_container_width=True, theme=None)

                with col2:

                    logger.info("Re-Entering plot option section to render export section")

                    # Add to the right column the export option
                    with st.expander("Export options"):
                        st.markdown("###### Export")
                        available_formats = ["png", "jpeg", "svg", "pdf"]
                        comparison_settings.format = st.selectbox(
                            "Select the format of the file",
                            available_formats,
                            index=available_formats.index(comparison_settings.format)
                            if comparison_settings.format
                            else 0,
                            key="format_comparison",
                        )
                        logger.debug(f"-> Export format {comparison_settings.format}")

                        comparison_settings.width = int(
                            st.number_input(
                                "Plot width",
                                min_value=10,
                                value=comparison_settings.width,
                            )
                        )
                        logger.debug(f"-> Plot width {comparison_settings.width}")

                        # Update the settings of plot layout to account for the user define width
                        fig.update_layout(
                            plot_bgcolor="#FFFFFF",
                            height=comparison_settings.height,
                            width=comparison_settings.width,
                            font=dict(size=comparison_settings.font_size),
                        )

                        st.download_button(
                            "Download plot",
                            data=fig.to_image(format=comparison_settings.format),
                            file_name=f"cycle_comparison_plot.{comparison_settings.format}",
                            on_click=lambda msg: logger.info(msg),
                            args=[f"DOWNLOAD cycle_plot.{comparison_settings.format}"],
                        )

    # If there are no experiments in the buffer suggest to the user to load data form the main page
    else:
        st.info(
            """**No experiment has been loaded yet** \n\n Please go to the file manager 
        page and procede to upload and properly edit the required experiment files before
        accessing this page."""
        )

    logger.info("FORCING RERUN AT END OF PAGE")
    force_update_once()

except st.runtime.scriptrunner.script_runner.RerunException:
    logger.info("EXPERIMENTAL RERUN CALLED")
    raise

except:
    logger.exception(
        f"Unexpected exception occurred during cycles plotter page execution:\n\n {traceback.print_exception(*sys.exc_info())}"
    )
    dump_index = 0
    while True:
        dump_file = f"./GES_echem_gui_dump_{dump_index}.pickle"
        if os.path.isfile(dump_file):
            dump_index += 1
        else:
            logger.critical(f"Dumping the content of the session state to '{dump_file}'")
            with open(dump_file, "wb") as file:
                pickle.dump(dict(st.session_state), file, protocol=pickle.HIGHEST_PROTOCOL)
            break
    raise

else:
    logger.debug("-> Cycles plotter page run completed succesfully")

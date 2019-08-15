from bokeh.plotting import figure, ColumnDataSource
from bokeh.models import DataRange1d, NumeralTickFormatter, BasicTicker
from bokeh.layouts import column
from bokeh.models.mappers import LinearColorMapper
from bokeh.palettes import all_palettes

import math
import time
import os

import pynvml

from jupyterlab_nvdashboard.utils import format_bytes

pynvml.nvmlInit()
ngpus = pynvml.nvmlDeviceGetCount()
gpu_handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(ngpus)]


def gpu(doc):
    fig = figure(title="GPU Utilization", sizing_mode="stretch_both", x_range=[0, 100])

    def get_utilization():
        return [
            pynvml.nvmlDeviceGetUtilizationRates(gpu_handles[i]).gpu
            for i in range(ngpus)
        ]

    gpu = get_utilization()
    y = list(range(len(gpu)))
    source = ColumnDataSource({"right": y, "gpu": gpu})
    mapper = LinearColorMapper(palette=all_palettes["RdYlBu"][4], low=0, high=100)

    fig.hbar(
        source=source,
        y="right",
        right="gpu",
        height=0.8,
        color={"field": "gpu", "transform": mapper},
    )

    fig.toolbar_location = None

    doc.title = "GPU Utilization [%]"
    doc.add_root(fig)

    def cb():
        source.data.update({"gpu": get_utilization()})

    doc.add_periodic_callback(cb, 200)


def gpu_mem(doc):
    def get_mem():
        return [pynvml.nvmlDeviceGetMemoryInfo(handle).used for handle in gpu_handles]

    def get_total():
        return pynvml.nvmlDeviceGetMemoryInfo(gpu_handles[0]).total

    fig = figure(
        title="GPU Memory", sizing_mode="stretch_both", x_range=[0, get_total()]
    )

    gpu = get_mem()

    y = list(range(len(gpu)))
    source = ColumnDataSource({"right": y, "gpu": gpu})
    mapper = LinearColorMapper(
        palette=all_palettes["RdYlBu"][8], low=0, high=get_total()
    )

    fig.hbar(
        source=source,
        y="right",
        right="gpu",
        height=0.8,
        color={"field": "gpu", "transform": mapper},
    )
    fig.xaxis[0].formatter = NumeralTickFormatter(format="0.0 b")
    fig.xaxis.major_label_orientation = -math.pi / 12

    fig.toolbar_location = None

    doc.title = "GPU Memory"
    doc.add_root(fig)

    def cb():
        mem = get_mem()
        source.data.update({"gpu": mem})
        fig.title.text = "GPU Memory: {}".format(format_bytes(sum(mem)))

    doc.add_periodic_callback(cb, 200)


def pci(doc):

    # Use device-0 to get "upper bound"
    pci_gen = pynvml.nvmlDeviceGetMaxPcieLinkGeneration(gpu_handles[0])
    pci_width = pynvml.nvmlDeviceGetMaxPcieLinkWidth(gpu_handles[0])
    pci_bw = {
        # PCIe-Generation: (BW-per-lane / Width / 2-directions)
        1: (250.0 / 1024.0 / 2.0),
        2: (500.0 / 1024.0 / 2.0),
        3: (985.0 / 1024.0 / 2.0),
        4: (2048.0 / 1024.0 / 2.0),
        5: (4032.0 / 1024.0 / 2.0),
        6: (8192.0 / 1024.0 / 2.0),
    }
    max_rxtx_tp = pci_width * pci_bw[pci_gen]
    tx_fig = figure(
        title="TX Bytes [GB/s]", sizing_mode="stretch_both", y_range=[0, max_rxtx_tp]
    )
    pci_tx = [
        pynvml.nvmlDeviceGetPcieThroughput(
            gpu_handles[i], pynvml.NVML_PCIE_UTIL_TX_BYTES
        )
        / (1024.0 * 1024.0)  # Convert KB/s -> GB/s
        for i in range(ngpus)
    ]
    left = list(range(len(pci_tx)))
    right = [l + 0.8 for l in left]
    source = ColumnDataSource({"left": left, "right": right, "pci-tx": pci_tx})
    mapper = LinearColorMapper(
        palette=all_palettes["RdYlBu"][4], low=0, high=max_rxtx_tp
    )

    tx_fig.quad(
        source=source,
        left="left",
        right="right",
        bottom=0,
        top="pci-tx",
        color={"field": "pci-tx", "transform": mapper},
    )

    rx_fig = figure(
        title="RX Bytes [GB/s]", sizing_mode="stretch_both", y_range=[0, max_rxtx_tp]
    )
    pci_rx = [
        pynvml.nvmlDeviceGetPcieThroughput(
            gpu_handles[i], pynvml.NVML_PCIE_UTIL_RX_BYTES
        )
        / (1024.0 * 1024.0)  # Convert KB/s -> GB/s
        for i in range(ngpus)
    ]
    left = list(range(len(pci_rx)))
    right = [l + 0.8 for l in left]
    source = ColumnDataSource({"left": left, "right": right, "pci-rx": pci_rx})
    mapper = LinearColorMapper(
        palette=all_palettes["RdYlBu"][4], low=0, high=max_rxtx_tp
    )

    rx_fig.quad(
        source=source,
        left="left",
        right="right",
        bottom=0,
        top="pci-rx",
        color={"field": "pci-rx", "transform": mapper},
    )

    doc.title = "PCI Throughput"
    doc.add_root(column(tx_fig, rx_fig, sizing_mode="stretch_both"))

    def cb():
        src_dict = {}
        src_dict["pci-tx"] = [
            pynvml.nvmlDeviceGetPcieThroughput(
                gpu_handles[i], pynvml.NVML_PCIE_UTIL_TX_BYTES
            )
            / (1024.0 * 1024.0)  # Convert KB/s -> GB/s
            for i in range(ngpus)
        ]
        src_dict["pci-rx"] = [
            pynvml.nvmlDeviceGetPcieThroughput(
                gpu_handles[i], pynvml.NVML_PCIE_UTIL_RX_BYTES
            )
            / (1024.0 * 1024.0)  # Convert KB/s -> GB/s
            for i in range(ngpus)
        ]
        source.data.update(src_dict)

    doc.add_periodic_callback(cb, 200)


def nvlink(doc):

    max_bw = 1024.0 * 1024.0 * 1024.0
    nlinks = pynvml.NVML_NVLINK_MAX_LINKS
    counter = 1
    # nvmlDeviceSetNvLinkUtilizationControl seems limited, using smi:
    os.system(
        "nvidia-smi nvlink --setcontrol " + str(counter) + "bz"
    )  # Get output in bytes

    tx_fig = figure(title="TX NVLink Bandwidth", sizing_mode="stretch_both")
    tx_fig.yaxis.formatter = NumeralTickFormatter(format="0.0b")
    nvlink_state = {}
    nvlink_state["tx"] = [
        sum(
            [
                pynvml.nvmlDeviceGetNvLinkUtilizationCounter(
                    gpu_handles[i], j, counter
                )["tx"]
                for j in range(nlinks)
            ]
        )
        for i in range(ngpus)
    ]
    nvlink_state["tx-ref"] = nvlink_state["tx"].copy()
    left = list(range(ngpus))
    right = [l + 0.8 for l in left]
    source = ColumnDataSource(
        {
            "left": left,
            "right": right,
            "count-tx": [0.0 for i in range(ngpus)],
            "count-rx": [0.0 for i in range(ngpus)],
        }
    )
    mapper = LinearColorMapper(palette=all_palettes["RdYlBu"][4], low=0, high=max_bw)

    tx_fig.quad(
        source=source,
        left="left",
        right="right",
        bottom=0,
        top="count-tx",
        color={"field": "count-tx", "transform": mapper},
    )

    rx_fig = figure(title="RX NVLink Bandwidth", sizing_mode="stretch_both")
    rx_fig.yaxis.formatter = NumeralTickFormatter(format="0.0b")
    nvlink_state["rx"] = [
        sum(
            [
                pynvml.nvmlDeviceGetNvLinkUtilizationCounter(
                    gpu_handles[i], j, counter
                )["rx"]
                for j in range(nlinks)
            ]
        )
        for i in range(ngpus)
    ]
    nvlink_state["rx-ref"] = nvlink_state["rx"].copy()

    rx_fig.quad(
        source=source,
        left="left",
        right="right",
        bottom=0,
        top="count-rx",
        color={"field": "count-rx", "transform": mapper},
    )

    doc.title = "NVLink Utilization Counters"
    doc.add_root(column(tx_fig, rx_fig, sizing_mode="stretch_both"))

    def cb():
        nvlink_state["tx-ref"] = nvlink_state["tx"].copy()
        nvlink_state["rx-ref"] = nvlink_state["rx"].copy()
        src_dict = {}
        nvlink_state["tx"] = [
            sum(
                [
                    pynvml.nvmlDeviceGetNvLinkUtilizationCounter(
                        gpu_handles[i], j, counter
                    )["tx"]
                    for j in range(nlinks)
                ]
            )
            for i in range(ngpus)
        ]
        nvlink_state["rx"] = [
            sum(
                [
                    pynvml.nvmlDeviceGetNvLinkUtilizationCounter(
                        gpu_handles[i], j, counter
                    )["rx"]
                    for j in range(nlinks)
                ]
            )
            for i in range(ngpus)
        ]
        src_dict["count-tx"] = [
            (a - b) * 2.0 for (a, b) in zip(nvlink_state["tx"], nvlink_state["tx-ref"])
        ]
        src_dict["count-rx"] = [
            (a - b) * 2.0 for (a, b) in zip(nvlink_state["rx"], nvlink_state["rx-ref"])
        ]
        source.data.update(src_dict)

    doc.add_periodic_callback(cb, 500)


def gpu_resource_timeline(doc):

    memory_list = [
        pynvml.nvmlDeviceGetMemoryInfo(handle).total / (1024 * 1024)
        for handle in gpu_handles
    ]
    gpu_mem_max = max(memory_list) * (1024 * 1024)
    gpu_mem_sum = sum(memory_list)

    # Shared X Range for all plots
    x_range = DataRange1d(follow="end", follow_interval=20000, range_padding=0)
    tools = "reset,xpan,xwheel_zoom"

    item_dict = {
        "time": [],
        "gpu-total": [],
        "memory-total": [],
        "rx-total": [],
        "tx-total": [],
    }
    for i in range(ngpus):
        item_dict["gpu-" + str(i)] = []
        item_dict["memory-" + str(i)] = []

    source = ColumnDataSource(item_dict)

    def _get_color(ind):
        color_list = [
            "blue",
            "red",
            "green",
            "black",
            "brown",
            "cyan",
            "orange",
            "pink",
            "purple",
            "gold",
        ]
        return color_list[ind % len(color_list)]

    memory_fig = figure(
        title="Memory Utilization (per Device)",
        sizing_mode="stretch_both",
        x_axis_type="datetime",
        y_range=[0, gpu_mem_max],
        x_range=x_range,
        tools=tools,
    )
    for i in range(ngpus):
        memory_fig.line(
            source=source, x="time", y="memory-" + str(i), color=_get_color(i)
        )
    memory_fig.yaxis.formatter = NumeralTickFormatter(format="0.0b")

    gpu_fig = figure(
        title="GPU Utilization (per Device) [%]",
        sizing_mode="stretch_both",
        x_axis_type="datetime",
        y_range=[0, 100],
        x_range=x_range,
        tools=tools,
    )
    for i in range(ngpus):
        gpu_fig.line(source=source, x="time", y="gpu-" + str(i), color=_get_color(i))

    tot_fig = figure(
        title="Total Utilization [%]",
        sizing_mode="stretch_both",
        x_axis_type="datetime",
        y_range=[0, 100],
        x_range=x_range,
        tools=tools,
    )
    tot_fig.line(
        source=source, x="time", y="gpu-total", color="blue", legend="Total-GPU"
    )
    tot_fig.line(
        source=source, x="time", y="memory-total", color="red", legend="Total-Memory"
    )
    tot_fig.legend.location = "top_left"

    pci_fig = figure(
        title="Total PCI Throughput [/s]",
        sizing_mode="stretch_both",
        x_axis_type="datetime",
        x_range=x_range,
        tools=tools,
    )
    pci_fig.line(source=source, x="time", y="tx-total", color="blue", legend="TX")
    pci_fig.line(source=source, x="time", y="rx-total", color="red", legend="RX")
    pci_fig.yaxis.formatter = NumeralTickFormatter(format="0.0b")
    pci_fig.legend.location = "top_left"

    doc.title = "Resource Timeline"
    doc.add_root(
        column(gpu_fig, memory_fig, tot_fig, pci_fig, sizing_mode="stretch_both")
    )

    last_time = time.time()

    def cb():
        nonlocal last_time
        now = time.time()
        src_dict = {"time": [now * 1000]}
        gpu_tot = 0
        mem_tot = 0
        tx_tot = 0
        rx_tot = 0
        for i in range(ngpus):
            gpu = pynvml.nvmlDeviceGetUtilizationRates(gpu_handles[i]).gpu
            mem = pynvml.nvmlDeviceGetMemoryInfo(gpu_handles[i]).used
            tx = (
                pynvml.nvmlDeviceGetPcieThroughput(
                    gpu_handles[i], pynvml.NVML_PCIE_UTIL_TX_BYTES
                )
                * 1024
            )
            rx = (
                pynvml.nvmlDeviceGetPcieThroughput(
                    gpu_handles[i], pynvml.NVML_PCIE_UTIL_RX_BYTES
                )
                * 1024
            )
            gpu_tot += gpu
            mem_tot += mem / (1024 * 1024)
            rx_tot += rx
            tx_tot += tx
            src_dict["gpu-" + str(i)] = [gpu]
            src_dict["memory-" + str(i)] = [mem]
        src_dict["gpu-total"] = [gpu_tot / ngpus]
        src_dict["memory-total"] = [(mem_tot / gpu_mem_sum) * 100]
        src_dict["tx-total"] = [tx_tot]
        src_dict["rx-total"] = [rx_tot]

        source.stream(src_dict, 1000)

        last_time = now

    doc.add_periodic_callback(cb, 200)

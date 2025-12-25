from __future__ import annotations
import plotly.express as px
import pandas as pd

def bar_bins(df_bins: pd.DataFrame, title: str):
    fig = px.bar(df_bins, x="bin", y="pct", text="count", title=title)
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_title="Return bins",
        yaxis_title="Ratio",
        uniformtext_minsize=8,
        uniformtext_mode="hide",
        height=360,
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig

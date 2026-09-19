"""Plotly figures, styled once so every chart on the page reads as one system.

Colour does exactly one job per chart:
  * one hue (blue) when bars are just ranked, so bar length carries the message
  * three fixed hues for the three root-cause buckets, assigned in a fixed order
    (blue, aqua, violet: validated for colour-vision deficiency at all pairs)
  * grey for de-emphasis, never for a category
Text never wears a data colour; labels stay in ink.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .logic import (CATEGORIES, CATEGORY_CODING, CATEGORY_ELIGIBILITY, CATEGORY_OPERATIONS,
                    CATEGORY_SHORT, CATEGORY_UNKNOWN)

SURFACE = "#ffffff"
INK = "#1f2933"
INK_2 = "#52606d"
MUTED = "#7b8794"
GRID = "#e4e7eb"
ACCENT = "#2a78d6"

CATEGORY_COLORS = {
    CATEGORY_ELIGIBILITY: "#2a78d6",
    CATEGORY_CODING: "#1baf7a",
    CATEGORY_OPERATIONS: "#4a3aa7",
    CATEGORY_UNKNOWN: "#7b8794",
}
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, sans-serif"
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


def _style(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=8, r=24, t=16, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=13, color=INK),
        hoverlabel=dict(bgcolor=INK, bordercolor=INK, font=dict(family=FONT, size=12, color="#ffffff")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=12, color=INK_2), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, showline=False,
                     tickfont=dict(color=MUTED, size=12), title_font=dict(color=INK_2, size=12))
    fig.update_yaxes(showgrid=False, zeroline=False, showline=False,
                     tickfont=dict(color=INK, size=13), title=None)
    return fig


def payer_wall_of_shame(rates: pd.DataFrame, overall_rate: float) -> go.Figure:
    """Horizontal bars, worst payer on top. One hue: the length is the message."""
    d = rates.sort_values("denial_rate_pct", ascending=True)
    custom = np.stack([d["denied_claims"], d["total_claims"], d["revenue_at_risk"]], axis=1)
    fig = go.Figure(go.Bar(
        x=d["denial_rate_pct"], y=d["Payer"], orientation="h",
        marker=dict(color=ACCENT, line=dict(width=0)),
        text=["%.1f%%" % v for v in d["denial_rate_pct"]],
        textposition="outside", textfont=dict(color=INK, size=13), cliponaxis=False,
        customdata=custom,
        hovertemplate=("<b>%{x:.1f}%</b> denial rate<br>"
                       "%{customdata[0]:,} of %{customdata[1]:,} claims denied<br>"
                       "$%{customdata[2]:,.0f} at risk<extra>%{y}</extra>"),
        name="Denial rate",
    ))
    xmax = max(float(d["denial_rate_pct"].max()) if len(d) else 0.0, overall_rate) * 1.3 + 1
    fig.add_vline(x=overall_rate, line_width=1, line_color=MUTED)
    fig.add_annotation(x=overall_rate, y=1.0, yref="paper", yanchor="bottom", showarrow=False,
                       text="All in view %.1f%%" % overall_rate, font=dict(size=12, color=INK_2))
    fig.update_layout(bargap=0.55, showlegend=False,
                      xaxis=dict(ticksuffix="%", range=[0, xmax], title="Denial rate"))
    return _style(fig, height=300)


def root_cause_donut(summary: pd.DataFrame) -> go.Figure:
    """Part-to-whole across the three buckets. Percent labels ride each slice; the table twin is on the page."""
    labels = [CATEGORY_SHORT.get(c, c) for c in summary["Root_Cause_Category"]]
    colors = [CATEGORY_COLORS.get(c, MUTED) for c in summary["Root_Cause_Category"]]
    total = int(summary["denied_claims"].sum())
    fig = go.Figure(go.Pie(
        labels=labels, values=summary["denied_claims"], hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=colors, line=dict(color=SURFACE, width=2)),
        textinfo="percent", textposition="outside", textfont=dict(color=INK, size=13),
        customdata=summary["revenue_at_risk"],
        hovertemplate="<b>%{value:,}</b> denials (%{percent})<br>$%{customdata:,.0f} at risk<extra>%{label}</extra>",
    ))
    fig.add_annotation(x=0.5, y=0.5, showarrow=False, align="center",
                       text="<span style='font-size:26px'><b>%s</b></span><br>"
                            "<span style='font-size:12px;color:%s'>denied claims</span>" % ("{:,}".format(total), INK_2),
                       font=dict(color=INK))
    _style(fig, height=300)
    fig.update_layout(margin=dict(l=8, r=8, t=8, b=8),
                      legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5))
    return fig


def denial_trend(monthly: pd.DataFrame) -> go.Figure:
    """One line, the denial rate by submission month, end-labelled. Hover shows the counts behind the rate."""
    custom = np.stack([monthly["denied_claims"], monthly["total_claims"]], axis=1)
    fig = go.Figure(go.Scatter(
        x=monthly["month_label"], y=monthly["denial_rate_pct"], mode="lines+markers",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=8, color=ACCENT, line=dict(color=SURFACE, width=2)),
        customdata=custom, name="Denial rate",
        hovertemplate="<b>%{y:.1f}%</b><br>%{customdata[0]:,} of %{customdata[1]:,} claims denied<extra></extra>",
    ))
    if len(monthly):
        last = monthly.iloc[-1]
        fig.add_annotation(x=last["month_label"], y=last["denial_rate_pct"], showarrow=False,
                           xanchor="left", xshift=12, text="<b>%.1f%%</b>" % last["denial_rate_pct"],
                           font=dict(size=13, color=INK))
    ymax = float(monthly["denial_rate_pct"].max()) * 1.3 + 1 if len(monthly) else 10
    fig.update_layout(hovermode="x unified", showlegend=False,
                      yaxis=dict(ticksuffix="%", range=[0, ymax], showgrid=True, gridcolor=GRID),
                      xaxis=dict(showgrid=False))
    return _style(fig, height=320)


def denial_trend_by_category(long: pd.DataFrame) -> go.Figure:
    """Three lines: each bucket's contribution to the monthly denial rate. They add up to the total."""
    fig = go.Figure()
    for cat in CATEGORIES:
        d = long[long["category"] == cat]
        fig.add_trace(go.Scatter(
            x=d["month_label"], y=d["rate_contribution_pct"], mode="lines+markers",
            name=CATEGORY_SHORT[cat],
            line=dict(color=CATEGORY_COLORS[cat], width=2),
            marker=dict(size=8, color=CATEGORY_COLORS[cat], line=dict(color=SURFACE, width=2)),
            customdata=np.stack([d["denied_claims"], d["total_claims"]], axis=1),
            hovertemplate="<b>%{y:.1f}%</b> of claims (%{customdata[0]:,} denials)<extra>" + CATEGORY_SHORT[cat] + "</extra>",
        ))
    ymax = float(long["rate_contribution_pct"].max()) * 1.35 + 0.5 if len(long) else 10
    fig.update_layout(hovermode="x unified", showlegend=True,
                      yaxis=dict(ticksuffix="%", range=[0, ymax], showgrid=True, gridcolor=GRID),
                      xaxis=dict(showgrid=False))
    return _style(fig, height=320)

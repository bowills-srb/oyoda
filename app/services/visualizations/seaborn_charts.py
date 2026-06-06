"""
Seaborn Visualizations for Rental Revenue Platform.

Professional statistical visualizations for:
- Market analysis and comparisons
- Seasonality patterns (heatmaps)
- Signal attribution
- Property performance analysis
- Operator benchmarking
- Price distribution analysis
"""

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime


# =============================================================================
# STYLE CONFIGURATION
# =============================================================================

# Custom color palette matching your brand
BRAND_COLORS = {
    'primary': '#0d7377',
    'primary_light': '#14a3a8',
    'secondary': '#d4a72c',
    'accent': '#2c3e50',
    'gray': '#718096',
    'light_gray': '#e2e8f0',
    'success': '#27ae60',
    'warning': '#f39c12',
    'danger': '#e74c3c',
}

# Seaborn palette
BRAND_PALETTE = [
    BRAND_COLORS['primary'],
    BRAND_COLORS['secondary'],
    BRAND_COLORS['accent'],
    BRAND_COLORS['success'],
    BRAND_COLORS['warning'],
    BRAND_COLORS['danger'],
]


def set_brand_style():
    """Set consistent brand styling for all charts."""
    sns.set_theme(style="whitegrid")
    sns.set_palette(BRAND_PALETTE)
    
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.size': 10,
        'axes.titlesize': 12,
        'axes.titleweight': 'bold',
        'axes.labelsize': 10,
        'axes.labelcolor': BRAND_COLORS['accent'],
        'axes.edgecolor': BRAND_COLORS['light_gray'],
        'xtick.color': BRAND_COLORS['gray'],
        'ytick.color': BRAND_COLORS['gray'],
        'grid.color': BRAND_COLORS['light_gray'],
        'grid.alpha': 0.7,
        'figure.facecolor': 'white',
        'axes.facecolor': 'white',
        'legend.frameon': False,
    })


# =============================================================================
# SEASONALITY VISUALIZATIONS
# =============================================================================

def create_seasonality_heatmap(
    data: Dict[str, Dict[str, float]],
    title: str = "Seasonality Pattern",
    value_label: str = "Value",
    figsize: Tuple[int, int] = (12, 6),
) -> BytesIO:
    """
    Create a heatmap showing seasonality patterns.
    
    Args:
        data: Dict of {property/market: {month: value}}
              e.g., {'Beach House': {'Jan': 0.3, 'Feb': 0.4, ...}}
        title: Chart title
        value_label: Label for the colorbar
        figsize: Figure size
    
    Returns:
        BytesIO buffer containing the PNG image
    """
    set_brand_style()
    
    # Convert to DataFrame
    df = pd.DataFrame(data).T
    
    # Ensure month order
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    df = df.reindex(columns=[m for m in months if m in df.columns])
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Create heatmap
    sns.heatmap(
        df,
        annot=True,
        fmt='.0%' if df.max().max() <= 1 else '.0f',
        cmap=sns.light_palette(BRAND_COLORS['primary'], as_cmap=True),
        linewidths=0.5,
        linecolor='white',
        cbar_kws={'label': value_label},
        ax=ax,
    )
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('')
    ax.set_ylabel('')
    
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_demand_calendar_heatmap(
    daily_data: Dict[str, float],
    year: int = 2026,
    title: str = "Daily Demand Pattern",
    figsize: Tuple[int, int] = (14, 4),
) -> BytesIO:
    """
    Create a calendar-style heatmap showing daily demand patterns.
    
    Args:
        daily_data: Dict of {'YYYY-MM-DD': demand_value}
        year: Year to display
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    # Create date range for the year
    dates = pd.date_range(f'{year}-01-01', f'{year}-12-31', freq='D')
    
    # Build data matrix (weeks x days)
    values = [daily_data.get(d.strftime('%Y-%m-%d'), 0) for d in dates]
    
    # Create DataFrame with week and day
    df = pd.DataFrame({
        'date': dates,
        'value': values,
        'week': [d.isocalendar()[1] for d in dates],
        'day': [d.weekday() for d in dates],
    })
    
    # Pivot to matrix
    matrix = df.pivot(index='day', columns='week', values='value')
    
    fig, ax = plt.subplots(figsize=figsize)
    
    sns.heatmap(
        matrix,
        cmap=sns.light_palette(BRAND_COLORS['primary'], as_cmap=True),
        linewidths=0.5,
        linecolor='white',
        cbar_kws={'label': 'Demand Index'},
        ax=ax,
    )
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_ylabel('Day of Week')
    ax.set_xlabel('Week of Year')
    ax.set_yticklabels(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# MARKET COMPARISON VISUALIZATIONS
# =============================================================================

def create_market_comparison_bars(
    data: List[Dict[str, Any]],
    x_field: str,
    y_field: str,
    title: str = "Market Comparison",
    y_label: str = "",
    show_values: bool = True,
    figsize: Tuple[int, int] = (10, 6),
    horizontal: bool = False,
) -> BytesIO:
    """
    Create a bar chart comparing markets or properties.
    
    Args:
        data: List of dicts with fields to plot
        x_field: Field name for x-axis (categories)
        y_field: Field name for y-axis (values)
        title: Chart title
        y_label: Y-axis label
        show_values: Whether to show value labels on bars
        figsize: Figure size
        horizontal: If True, create horizontal bars
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(data)
    df = df.sort_values(y_field, ascending=horizontal)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if horizontal:
        bars = sns.barplot(
            data=df, y=x_field, x=y_field, 
            color=BRAND_COLORS['primary'], ax=ax
        )
        if show_values:
            for i, (val, name) in enumerate(zip(df[y_field], df[x_field])):
                ax.text(val + df[y_field].max() * 0.01, i, f'{val:,.0f}', 
                       va='center', fontsize=9, color=BRAND_COLORS['accent'])
    else:
        bars = sns.barplot(
            data=df, x=x_field, y=y_field,
            color=BRAND_COLORS['primary'], ax=ax
        )
        if show_values:
            for i, val in enumerate(df[y_field]):
                ax.text(i, val + df[y_field].max() * 0.01, f'{val:,.0f}',
                       ha='center', fontsize=9, color=BRAND_COLORS['accent'])
        plt.xticks(rotation=45, ha='right')
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('')
    ax.set_ylabel(y_label)
    
    # Remove top and right spines
    sns.despine()
    
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_adr_occupancy_scatter(
    data: List[Dict[str, Any]],
    title: str = "ADR vs Occupancy Analysis",
    color_by: Optional[str] = None,
    size_by: Optional[str] = None,
    figsize: Tuple[int, int] = (10, 8),
) -> BytesIO:
    """
    Create a scatter plot of ADR vs Occupancy.
    
    Args:
        data: List of dicts with 'adr', 'occupancy', and optional grouping fields
        title: Chart title
        color_by: Field to color points by (e.g., 'property_type', 'market')
        size_by: Field to size points by (e.g., 'revenue', 'bedrooms')
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(data)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    scatter_kwargs = {
        'data': df,
        'x': 'adr',
        'y': 'occupancy',
        'ax': ax,
        'alpha': 0.7,
    }
    
    if color_by and color_by in df.columns:
        scatter_kwargs['hue'] = color_by
        scatter_kwargs['palette'] = BRAND_PALETTE
    else:
        scatter_kwargs['color'] = BRAND_COLORS['primary']
    
    if size_by and size_by in df.columns:
        scatter_kwargs['size'] = size_by
        scatter_kwargs['sizes'] = (50, 400)
    else:
        scatter_kwargs['s'] = 100
    
    sns.scatterplot(**scatter_kwargs)
    
    # Add revenue contours (ADR * Occupancy * 365)
    adr_range = np.linspace(df['adr'].min() * 0.8, df['adr'].max() * 1.2, 100)
    for rev_target in [50000, 100000, 150000, 200000]:
        occ_for_rev = rev_target / (adr_range * 365)
        valid = (occ_for_rev >= 0) & (occ_for_rev <= 1)
        ax.plot(adr_range[valid], occ_for_rev[valid], '--', 
                color=BRAND_COLORS['light_gray'], alpha=0.5, linewidth=1)
        if valid.any():
            idx = np.where(valid)[0][-1]
            ax.annotate(f'${rev_target/1000:.0f}K', 
                       (adr_range[idx], occ_for_rev[idx]),
                       fontsize=8, color=BRAND_COLORS['gray'])
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('Average Daily Rate ($)')
    ax.set_ylabel('Occupancy Rate')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y:.0%}'))
    
    if color_by:
        ax.legend(title=color_by.replace('_', ' ').title(), 
                 bbox_to_anchor=(1.02, 1), loc='upper left')
    
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# SIGNAL ATTRIBUTION VISUALIZATIONS
# =============================================================================

def create_signal_waterfall(
    base_value: float,
    signals: List[Dict[str, Any]],
    title: str = "Revenue Attribution",
    figsize: Tuple[int, int] = (10, 6),
) -> BytesIO:
    """
    Create a waterfall chart showing signal contributions.
    
    Args:
        base_value: Starting base value
        signals: List of {'name': str, 'impact': float (as decimal)}
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Calculate cumulative values
    names = ['Base'] + [s['name'] for s in signals] + ['Total']
    
    values = [base_value]
    running = base_value
    for s in signals:
        impact = base_value * s['impact']
        values.append(impact)
        running += impact
    values.append(running)
    
    # Calculate bar positions
    cumulative = [0]
    for i, v in enumerate(values[:-1]):
        if i == 0:
            cumulative.append(v)
        else:
            cumulative.append(cumulative[-1] + v)
    
    # Colors
    colors = [BRAND_COLORS['gray']]  # Base
    for s in signals:
        colors.append(BRAND_COLORS['success'] if s['impact'] >= 0 else BRAND_COLORS['danger'])
    colors.append(BRAND_COLORS['primary'])  # Total
    
    # Plot bars
    bottoms = [0] + cumulative[1:-1] + [0]
    for i, (name, val, bottom, color) in enumerate(zip(names, values, bottoms, colors)):
        if i == 0 or i == len(names) - 1:
            # Base and Total bars start from 0
            ax.bar(i, val if i == 0 else cumulative[-1], color=color, width=0.6)
        else:
            # Impact bars are floating
            ax.bar(i, val, bottom=bottom, color=color, width=0.6)
        
        # Value labels
        label_y = bottom + val / 2 if i not in [0, len(names)-1] else val / 2
        if i == len(names) - 1:
            label_y = cumulative[-1] / 2
        
        if i == 0:
            label = f'${val:,.0f}'
        elif i == len(names) - 1:
            label = f'${cumulative[-1]:,.0f}'
        else:
            label = f'{signals[i-1]["impact"]:+.0%}'
        
        ax.text(i, label_y, label, ha='center', va='center', 
               fontsize=9, fontweight='bold', color='white')
    
    # Connect bars with lines
    for i in range(len(names) - 1):
        if i == 0:
            y = values[0]
        else:
            y = cumulative[i] + values[i]
        ax.plot([i + 0.3, i + 0.7], [y, y], color=BRAND_COLORS['gray'], 
               linewidth=1, linestyle='--', alpha=0.5)
    
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha='right')
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_ylabel('Projected Revenue ($)')
    
    # Format y-axis
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'${y/1000:.0f}K'))
    
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_signal_correlation_heatmap(
    correlation_matrix: pd.DataFrame,
    title: str = "Signal Correlation Matrix",
    figsize: Tuple[int, int] = (10, 8),
) -> BytesIO:
    """
    Create a correlation heatmap for signals.
    
    Args:
        correlation_matrix: DataFrame with correlation values
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Create diverging colormap
    cmap = sns.diverging_palette(220, 20, as_cmap=True)
    
    # Create mask for upper triangle
    mask = np.triu(np.ones_like(correlation_matrix, dtype=bool))
    
    sns.heatmap(
        correlation_matrix,
        mask=mask,
        cmap=cmap,
        vmin=-1, vmax=1,
        center=0,
        annot=True,
        fmt='.2f',
        linewidths=0.5,
        linecolor='white',
        cbar_kws={'label': 'Correlation'},
        ax=ax,
    )
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_confidence_gauge(
    confidence: float,
    title: str = "Projection Confidence",
    figsize: Tuple[int, int] = (6, 4),
) -> BytesIO:
    """
    Create a gauge chart showing confidence level.
    
    Args:
        confidence: Confidence value (0-1)
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    fig, ax = plt.subplots(figsize=figsize, subplot_kw={'projection': 'polar'})
    
    # Create gauge (half circle)
    theta = np.linspace(0, np.pi, 100)
    
    # Background arc
    ax.fill_between(theta, 0.6, 1.0, color=BRAND_COLORS['light_gray'], alpha=0.3)
    
    # Colored sections
    sections = [
        (0, 0.33, BRAND_COLORS['danger']),
        (0.33, 0.66, BRAND_COLORS['warning']),
        (0.66, 1.0, BRAND_COLORS['success']),
    ]
    
    for start, end, color in sections:
        section_theta = np.linspace(np.pi * (1 - end), np.pi * (1 - start), 50)
        ax.fill_between(section_theta, 0.6, 1.0, color=color, alpha=0.3)
    
    # Confidence indicator
    conf_angle = np.pi * (1 - confidence)
    ax.annotate('', xy=(conf_angle, 0.9), xytext=(np.pi/2, 0),
                arrowprops=dict(arrowstyle='->', color=BRAND_COLORS['accent'], lw=3))
    
    # Labels
    ax.text(np.pi/2, 0.3, f'{confidence:.0%}', ha='center', va='center',
           fontsize=24, fontweight='bold', color=BRAND_COLORS['primary'])
    ax.text(np.pi/2, 0.05, title, ha='center', va='center',
           fontsize=10, color=BRAND_COLORS['gray'])
    
    # Clean up
    ax.set_ylim(0, 1)
    ax.set_xlim(0, np.pi)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines['polar'].set_visible(False)
    
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# PRICE DISTRIBUTION VISUALIZATIONS
# =============================================================================

def create_price_distribution(
    data: List[Dict[str, Any]],
    price_field: str = 'adr',
    group_by: Optional[str] = None,
    title: str = "Price Distribution",
    figsize: Tuple[int, int] = (10, 6),
) -> BytesIO:
    """
    Create a violin/box plot showing price distribution.
    
    Args:
        data: List of dicts with price data
        price_field: Field containing price values
        group_by: Optional field to group by
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(data)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if group_by and group_by in df.columns:
        sns.violinplot(
            data=df, x=group_by, y=price_field,
            palette=BRAND_PALETTE, ax=ax, inner='box'
        )
        plt.xticks(rotation=45, ha='right')
    else:
        sns.violinplot(
            data=df, y=price_field,
            color=BRAND_COLORS['primary'], ax=ax, inner='box'
        )
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('')
    ax.set_ylabel('Average Daily Rate ($)')
    
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


def create_revenue_distribution(
    data: List[Dict[str, Any]],
    revenue_field: str = 'revenue',
    title: str = "Revenue Distribution",
    show_percentiles: bool = True,
    figsize: Tuple[int, int] = (10, 5),
) -> BytesIO:
    """
    Create a histogram with KDE showing revenue distribution.
    
    Args:
        data: List of dicts with revenue data
        revenue_field: Field containing revenue values
        title: Chart title
        show_percentiles: Whether to show percentile lines
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(data)
    values = df[revenue_field]
    
    fig, ax = plt.subplots(figsize=figsize)
    
    sns.histplot(values, kde=True, color=BRAND_COLORS['primary'], 
                alpha=0.6, ax=ax, stat='density')
    
    if show_percentiles:
        percentiles = [25, 50, 75]
        colors = [BRAND_COLORS['warning'], BRAND_COLORS['success'], BRAND_COLORS['warning']]
        labels = ['25th', 'Median', '75th']
        
        for pct, color, label in zip(percentiles, colors, labels):
            val = np.percentile(values, pct)
            ax.axvline(val, color=color, linestyle='--', linewidth=2, alpha=0.8)
            ax.text(val, ax.get_ylim()[1] * 0.95, f'{label}\n${val:,.0f}',
                   ha='center', fontsize=8, color=color)
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('Annual Revenue ($)')
    ax.set_ylabel('Density')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x/1000:.0f}K'))
    
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# OPERATOR BENCHMARKING VISUALIZATIONS
# =============================================================================

def create_operator_benchmark(
    operators: List[Dict[str, Any]],
    metrics: List[str] = ['adr_delta', 'occupancy_delta', 'revpar_delta'],
    title: str = "Operator Performance Benchmark",
    figsize: Tuple[int, int] = (12, 6),
) -> BytesIO:
    """
    Create a grouped bar chart comparing operator performance.
    
    Args:
        operators: List of dicts with operator name and metric values
        metrics: List of metric fields to compare
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(operators)
    
    # Melt for grouped bar chart
    df_melted = df.melt(
        id_vars=['name'], 
        value_vars=metrics,
        var_name='Metric',
        value_name='Value'
    )
    
    # Clean metric names
    df_melted['Metric'] = df_melted['Metric'].str.replace('_delta', '').str.replace('_', ' ').str.title()
    
    fig, ax = plt.subplots(figsize=figsize)
    
    sns.barplot(
        data=df_melted, x='name', y='Value', hue='Metric',
        palette=BRAND_PALETTE[:len(metrics)], ax=ax
    )
    
    # Add zero line
    ax.axhline(0, color=BRAND_COLORS['gray'], linestyle='-', linewidth=1)
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('')
    ax.set_ylabel('Performance vs Market (%)')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y:+.0%}'))
    ax.legend(title='', bbox_to_anchor=(1.02, 1), loc='upper left')
    
    plt.xticks(rotation=45, ha='right')
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# TREND ANALYSIS VISUALIZATIONS
# =============================================================================

def create_trend_line(
    data: List[Dict[str, Any]],
    x_field: str,
    y_field: str,
    group_by: Optional[str] = None,
    title: str = "Trend Analysis",
    y_label: str = "",
    show_confidence: bool = True,
    figsize: Tuple[int, int] = (12, 6),
) -> BytesIO:
    """
    Create a line chart with optional confidence intervals.
    
    Args:
        data: List of dicts with time series data
        x_field: Field for x-axis (usually date/time)
        y_field: Field for y-axis (values)
        group_by: Optional field to create multiple lines
        title: Chart title
        y_label: Y-axis label
        show_confidence: Whether to show confidence bands
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(data)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if group_by and group_by in df.columns:
        sns.lineplot(
            data=df, x=x_field, y=y_field, hue=group_by,
            palette=BRAND_PALETTE, ax=ax, marker='o'
        )
        ax.legend(title=group_by.replace('_', ' ').title(),
                 bbox_to_anchor=(1.02, 1), loc='upper left')
    else:
        if show_confidence:
            # Calculate rolling stats for confidence band
            sns.lineplot(
                data=df, x=x_field, y=y_field,
                color=BRAND_COLORS['primary'], ax=ax, marker='o'
            )
        else:
            sns.lineplot(
                data=df, x=x_field, y=y_field,
                color=BRAND_COLORS['primary'], ax=ax, marker='o'
            )
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('')
    ax.set_ylabel(y_label)
    
    plt.xticks(rotation=45, ha='right')
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# AMENITY ANALYSIS VISUALIZATIONS
# =============================================================================

def create_amenity_impact_chart(
    amenities: List[Dict[str, Any]],
    title: str = "Amenity Revenue Impact",
    figsize: Tuple[int, int] = (10, 8),
) -> BytesIO:
    """
    Create a horizontal bar chart showing amenity impacts.
    
    Args:
        amenities: List of {'name': str, 'impact': float, 'confidence': str}
        title: Chart title
        figsize: Figure size
    
    Returns:
        BytesIO buffer
    """
    set_brand_style()
    
    df = pd.DataFrame(amenities)
    df = df.sort_values('impact', ascending=True)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Color by positive/negative
    colors = [BRAND_COLORS['success'] if x >= 0 else BRAND_COLORS['danger'] 
              for x in df['impact']]
    
    bars = ax.barh(df['name'], df['impact'], color=colors, alpha=0.8)
    
    # Add value labels
    for bar, val, conf in zip(bars, df['impact'], df.get('confidence', ['Medium'] * len(df))):
        x_pos = val + 0.01 if val >= 0 else val - 0.01
        ha = 'left' if val >= 0 else 'right'
        ax.text(x_pos, bar.get_y() + bar.get_height()/2, 
               f'{val:+.0%}', va='center', ha=ha, fontsize=9,
               color=BRAND_COLORS['accent'])
    
    # Add zero line
    ax.axvline(0, color=BRAND_COLORS['gray'], linestyle='-', linewidth=1)
    
    ax.set_title(title, fontsize=14, fontweight='bold', color=BRAND_COLORS['accent'])
    ax.set_xlabel('Revenue Impact (%)')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:+.0%}'))
    
    sns.despine()
    plt.tight_layout()
    
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    
    return buf


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def save_chart_to_file(buf: BytesIO, filepath: str) -> str:
    """Save a chart buffer to a file."""
    with open(filepath, 'wb') as f:
        f.write(buf.getvalue())
    return filepath


def charts_to_pdf(
    charts: List[Tuple[BytesIO, str]],
    output_path: str,
    title: str = "Market Analysis Report",
) -> str:
    """
    Combine multiple charts into a PDF report.
    
    Args:
        charts: List of (BytesIO buffer, title) tuples
        output_path: Where to save the PDF
        title: Report title
    
    Returns:
        Path to generated PDF
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Image, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    story.append(Paragraph(title, styles['Title']))
    story.append(Spacer(1, 20))
    
    # Add each chart
    for buf, chart_title in charts:
        story.append(Paragraph(chart_title, styles['Heading2']))
        story.append(Spacer(1, 10))
        story.append(Image(buf, width=7*inch, height=4*inch))
        story.append(Spacer(1, 20))
    
    doc.build(story)
    return output_path

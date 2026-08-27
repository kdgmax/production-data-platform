"""Streamlit presentation layer for platform monitoring."""

from __future__ import annotations

import os

from data_platform.monitoring import get_monitoring_snapshot


def render_dashboard() -> None:
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Data Platform Operations", page_icon="📊", layout="wide")
    st.title("Data Platform Operations")
    st.caption("Pipeline reliability, throughput, data quality, and file lineage")

    default_url = os.getenv("DATA_PLATFORM_DATABASE_URL", "sqlite:///warehouse.db")
    database_url = st.sidebar.text_input("Database URL", value=default_url, type="password")
    success_slo = st.sidebar.slider("Success-rate SLO", 0.0, 100.0, 95.0, 0.5)
    recent_limit = st.sidebar.slider("Recent runs", 10, 200, 50, 10)

    try:
        snapshot = get_monitoring_snapshot(
            database_url,
            recent_limit=recent_limit,
            success_slo_percent=success_slo,
        )
    # The UI boundary converts connection and query failures into an actionable message.
    except Exception as error:  # noqa: BLE001
        st.error(f"Unable to load monitoring data: {error}")
        st.stop()

    status = snapshot["platform_status"]
    if status == "healthy":
        st.success("Platform status: healthy")
    elif status == "degraded":
        st.error("Platform status: degraded")
        for alert in snapshot["alerts"]:
            st.warning(alert)
    else:
        st.info("Platform status: no pipeline runs recorded")

    overview = snapshot["overview"]
    first_row = st.columns(4)
    first_row[0].metric("Run success rate", f'{overview["success_rate_percent"]:.2f}%')
    first_row[1].metric("Pipeline runs", f'{overview["total_runs"]:,}')
    first_row[2].metric("Input rows", f'{overview["total_input_rows"]:,}')
    first_row[3].metric("Landed files", f'{overview["total_files"]:,}')

    second_row = st.columns(4)
    second_row[0].metric("Accepted rows", f'{overview["accepted_rows"]:,}')
    second_row[1].metric("Quarantined rows", f'{overview["quarantined_rows"]:,}')
    second_row[2].metric("Quarantine rate", f'{overview["quarantine_rate_percent"]:.2f}%')
    second_row[3].metric("Deduplicated rows", f'{overview["deduplicated_rows"]:,}')

    trend_tab, runs_tab, quality_tab, files_tab = st.tabs(
        ["Trends", "Recent runs", "Quality failures", "File manifest"]
    )
    with trend_tab:
        if snapshot["daily_trends"]:
            trends = pd.DataFrame(snapshot["daily_trends"])
            st.subheader("Daily run outcomes")
            st.bar_chart(trends, x="date", y=["succeeded", "failed"], stack=True)
            st.subheader("Daily input volume")
            st.line_chart(trends, x="date", y="input_rows")

            st.subheader("Execution paths")
            st.dataframe(snapshot["trigger_breakdown"], width="stretch", hide_index=True)
        else:
            st.info("Run a pipeline to populate trend data.")

    with runs_tab:
        st.dataframe(snapshot["recent_runs"], width="stretch", hide_index=True)

    with quality_tab:
        if snapshot["quality_failures"]:
            st.dataframe(snapshot["quality_failures"], width="stretch", hide_index=True)
        else:
            st.success("No persisted quality failures")

    with files_tab:
        st.dataframe(snapshot["manifest_status"], width="stretch", hide_index=True)


if __name__ == "__main__":
    render_dashboard()

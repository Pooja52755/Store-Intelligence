import React, { useState, useEffect } from 'react';
import './App.css';
import Heatmap from './Heatmap';

function App() {
  const [storeId] = useState('STORE_BLR_002');
  const [metrics, setMetrics] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // Connect to WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//localhost:8000/ws/${storeId}`;
    
    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'metrics') {
        setMetrics(data.metrics);
      }
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setConnected(false);
    };
    
    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    };
    
    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [storeId]);

  // Fetch metrics on load and periodically
  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const response = await fetch(`http://localhost:8000/stores/${storeId}/metrics`);
        if (response.ok) {
          const data = await response.json();
          setMetrics(data);
        }
      } catch (error) {
        console.error('Error fetching metrics:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000); // Update every 30s
    return () => clearInterval(interval);
  }, [storeId]);

  // Fetch heatmap data
  useEffect(() => {
    const fetchHeatmap = async () => {
      try {
        const response = await fetch(`http://localhost:8000/stores/${storeId}/heatmap`);
        if (response.ok) {
          const data = await response.json();
          setHeatmapData(data);
        }
      } catch (error) {
        console.error('Error fetching heatmap:', error);
      }
    };

    fetchHeatmap();
    const interval = setInterval(fetchHeatmap, 30000);
    return () => clearInterval(interval);
  }, [storeId]);

  // Fetch funnel
  useEffect(() => {
    const fetchFunnel = async () => {
      try {
        const response = await fetch(`http://localhost:8000/stores/${storeId}/funnel`);
        if (response.ok) {
          setFunnel(await response.json());
        }
      } catch (error) {
        console.error('Error fetching funnel:', error);
      }
    };
    fetchFunnel();
    const interval = setInterval(fetchFunnel, 30000);
    return () => clearInterval(interval);
  }, [storeId]);

  // Fetch anomalies
  useEffect(() => {
    const fetchAnomalies = async () => {
      try {
        const response = await fetch(`http://localhost:8000/stores/${storeId}/anomalies`);
        if (response.ok) {
          const data = await response.json();
          setAnomalies(data.anomalies || []);
        }
      } catch (error) {
        console.error('Error fetching anomalies:', error);
      }
    };

    fetchAnomalies();
    const interval = setInterval(fetchAnomalies, 60000); // Update every minute
    return () => clearInterval(interval);
  }, [storeId]);

  if (loading) {
    return <div className="loading">Loading dashboard...</div>;
  }

  return (
    <div className="App">
      <header className="App-header">
        <h1>Store Intelligence Dashboard</h1>
        <div className="status">
          <span className={`indicator ${connected ? 'connected' : 'disconnected'}`}></span>
          {connected ? 'Live' : 'Offline'}
        </div>
      </header>

      <main className="dashboard">
        <section className="metrics-section">
          <h2>Real-Time Metrics - {storeId}</h2>
          {metrics && (
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">Unique Visitors Today</div>
                <div className="metric-value">{metrics.unique_visitors}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Conversion Rate</div>
                <div className="metric-value">{(metrics.conversion_rate * 100).toFixed(1)}%</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Queue Depth</div>
                <div className="metric-value">{metrics.current_queue_depth}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Abandonment Rate</div>
                <div className="metric-value">{(metrics.abandonment_rate * 100).toFixed(1)}%</div>
              </div>
            </div>
          )}
        </section>

        <section className="funnel-section">
          <h2>Conversion Funnel</h2>
          {funnel && (
            <div className="funnel-grid">
              <div className="metric-card">
                <div className="metric-label">Unique Visitors (today)</div>
                <div className="metric-value">{funnel.unique_visitors}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Entry Sessions (today)</div>
                <div className="metric-value">{funnel.entry_sessions}</div>
              </div>
              {funnel.funnel.map((stage) => (
                <div key={stage.stage} className="metric-card">
                  <div className="metric-label">{stage.stage}</div>
                  <div className="metric-value">{stage.count}</div>
                  <div className="metric-label">Drop-off: {stage.dropoff_pct}%</div>
                </div>
              ))}
              <div className="metric-card">
                <div className="metric-label">Funnel Conversion</div>
                <div className="metric-value">{(funnel.conversion_rate * 100).toFixed(1)}%</div>
              </div>
            </div>
          )}
        </section>

        <section className="heatmap-section">
          <h2>Zone Heatmap</h2>
          {heatmapData && <Heatmap data={heatmapData} />}
        </section>

        <section className="anomalies-section">
          <h2>Active Anomalies</h2>
          {anomalies.length === 0 ? (
            <div className="no-anomalies">✓ No anomalies detected</div>
          ) : (
            <div className="anomalies-list">
              {anomalies.map((anomaly, idx) => (
                <div key={idx} className={`anomaly-card severity-${anomaly.severity.toLowerCase()}`}>
                  <div className="anomaly-type">{anomaly.type}</div>
                  <div className="anomaly-severity">{anomaly.severity}</div>
                  <div className="anomaly-message">{anomaly.suggested_action}</div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;

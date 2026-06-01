import React, { useState, useEffect } from 'react';
import './App.css';
import Heatmap from './Heatmap';

const apiHost = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
const apiBase = `http://${apiHost}:8000`;

function App() {
  const [storeId] = useState('STORE_BLR_002');
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);

  // Video Upload States
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [processingRunId, setProcessingRunId] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [processingError, setProcessingError] = useState(null);
  const [processingLogs, setProcessingLogs] = useState('');
  const [cameraId, setCameraId] = useState('CAM_UPLOAD');

  // Connect to WebSocket
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${apiHost}:8000/ws/${storeId}`;
    
    let ws;
    try {
      ws = new WebSocket(wsUrl);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setConnected(true);
      };
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'metrics') {
          // Only update if viewing live/latest run
          if (!selectedRunId) {
            setMetrics(data.metrics);
          }
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
    } catch (e) {
      console.warn('Could not establish WebSocket connection', e);
    }
    
    return () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [storeId, selectedRunId]);

  // Fetch available runs
  const fetchRuns = async () => {
    try {
      const response = await fetch(`${apiBase}/runs?store_id=${storeId}`);
      if (response.ok) {
        const data = await response.json();
        setRuns(data.runs || []);
        // Automatically default to the latest run if none selected
        if (!selectedRunId && data.runs && data.runs.length > 0) {
          // Find first run that is COMPLETED or has events, or just first in list
          const firstCompleted = data.runs.find(r => r.status === 'COMPLETED' || r.total_events > 0);
          if (firstCompleted) {
            setSelectedRunId(firstCompleted.run_id);
          } else {
            setSelectedRunId(data.runs[0].run_id);
          }
        }
      }
    } catch (error) {
      console.error('Error fetching runs:', error);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 8000);
    return () => clearInterval(interval);
  }, [storeId]);

  // Fetch metrics, heatmap, funnel, anomalies based on selectedRunId
  const fetchDashboardData = async () => {
    if (!selectedRunId) return;
    
    try {
      const queryParams = `?run_id=${selectedRunId}`;
      
      // Fetch metrics
      const mRes = await fetch(`${apiBase}/stores/${storeId}/metrics${queryParams}`);
      if (mRes.ok) setMetrics(await mRes.json());
      
      // Fetch heatmap
      const hRes = await fetch(`${apiBase}/stores/${storeId}/heatmap${queryParams}`);
      if (hRes.ok) setHeatmapData(await hRes.json());
      
      // Fetch funnel
      const fRes = await fetch(`${apiBase}/stores/${storeId}/funnel${queryParams}`);
      if (fRes.ok) setFunnel(await fRes.json());
      
      // Fetch anomalies
      const aRes = await fetch(`${apiBase}/stores/${storeId}/anomalies${queryParams}`);
      if (aRes.ok) {
        const data = await aRes.json();
        setAnomalies(data.anomalies || []);
      }
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, [storeId, selectedRunId]);

  // Active processing run polling
  useEffect(() => {
    if (!processingRunId) return;

    const pollStatus = async () => {
      try {
        const response = await fetch(`${apiBase}/runs/${processingRunId}?store_id=${storeId}`);
        if (response.ok) {
          const run = await response.json();
          setProcessingStatus(run.status);
          if (run.error) {
            setProcessingError(run.error);
          }
          if (run.stderr) {
            setProcessingLogs(run.stderr);
          }
          
          if (run.status === 'COMPLETED' || run.status === 'FAILED') {
            setProcessingRunId(null);
            fetchRuns();
            setSelectedRunId(run.run_id);
          }
        }
      } catch (error) {
        console.error('Error polling run status:', error);
      }
    };

    pollStatus();
    const interval = setInterval(pollStatus, 2000);
    return () => clearInterval(interval);
  }, [processingRunId, storeId]);

  // Video Upload Handler
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadFile) return;

    setUploading(true);
    setProcessingError(null);
    setProcessingLogs('');
    setProcessingStatus('UPLOADING');

    const formData = new FormData();
    formData.append('file', uploadFile);
    formData.append('store_id', storeId);
    formData.append('camera_id', cameraId);

    try {
      const response = await fetch(`${apiBase}/upload-video`, {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const result = await response.json();
        setProcessingRunId(result.run_id);
        setProcessingStatus(result.status);
        setUploadFile(null);
      } else {
        const err = await response.json();
        setProcessingError(err.message || 'Upload failed');
        setProcessingStatus('FAILED');
      }
    } catch (error) {
      setProcessingError(error.message || 'Upload request failed');
      setProcessingStatus('FAILED');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Store Intelligence Dashboard</h1>
        <div className="header-controls">
          <div className="run-selector-container">
            <label htmlFor="run-select">Selected Run: </label>
            <select 
              id="run-select" 
              value={selectedRunId} 
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="run-select"
            >
              <option value="">-- Choose Pipeline Run --</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {new Date(r.created_at).toLocaleString()} | {r.status} | {r.total_events} events ({r.run_id.slice(0,8)})
                </option>
              ))}
            </select>
            <button onClick={fetchRuns} className="refresh-button">↻</button>
          </div>
          <div className="status">
            <span className={`indicator ${connected ? 'connected' : 'disconnected'}`}></span>
            {connected ? 'Live' : 'Offline'}
          </div>
        </div>
      </header>

      <main className="dashboard">
        {/* Upload CCTV Video Section */}
        <section className="upload-section">
          <h2>Upload CCTV Video Clip</h2>
          <form onSubmit={handleUpload} className="upload-form">
            <div className="form-group">
              <label>Select Video (.mp4): </label>
              <input 
                type="file" 
                accept="video/mp4" 
                onChange={(e) => setUploadFile(e.target.files[0])}
                className="file-input"
                required
              />
            </div>
            <div className="form-group">
              <label>Camera ID: </label>
              <select 
                value={cameraId} 
                onChange={(e) => setCameraId(e.target.value)}
                className="camera-select"
              >
                <option value="CAM1">Camera 1 (Skincare Entry)</option>
                <option value="CAM2">Camera 2 (Makeup Row)</option>
                <option value="CAM3">Camera 3 (Inner Aisle)</option>
                <option value="CAM4">Camera 4 (Fragrance/Queue)</option>
                <option value="CAM5">Camera 5 (Counters)</option>
                <option value="CAM_UPLOAD">Custom Upload CAM</option>
              </select>
            </div>
            <button 
              type="submit" 
              disabled={uploading || !!processingRunId || !uploadFile}
              className="upload-submit-btn"
            >
              {uploading ? 'Uploading Video...' : 'Analyze CCTV Clip'}
            </button>
          </form>

          {/* Active Job Progress Feedback */}
          {(processingStatus || processingError) && (
            <div className={`upload-status-box status-${(processingStatus || '').toLowerCase()}`}>
              <h3>Video Processing Status</h3>
              <div className="status-indicator">
                <span className="status-label">State: </span>
                <span className={`status-badge state-${(processingStatus || '').toLowerCase()}`}>
                  {processingStatus}
                </span>
              </div>
              {processingRunId && (
                <div className="spinner-container">
                  <div className="loading-spinner"></div>
                  <p className="loading-text">YOLOv8 Detection and ByteTrack Re-ID running on CPU...</p>
                </div>
              )}
              {processingError && (
                <div className="error-message">
                  <strong>Error: </strong> {processingError}
                </div>
              )}
              {processingLogs && (
                <div className="logs-container">
                  <strong>Stderr Output:</strong>
                  <pre className="logs-output">{processingLogs}</pre>
                </div>
              )}
            </div>
          )}
        </section>

        {loading ? (
          <div className="loading-card">Select a run from the dropdown above to load retail metrics</div>
        ) : (
          <>
            <section className="metrics-section">
              <h2>Retail Metrics Summary</h2>
              {metrics && (
                <div className="metrics-grid">
                  <div className="metric-card">
                    <div className="metric-label">Unique Visitors</div>
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
              <h2>Conversion Funnel Analysis</h2>
              {funnel && (
                <div className="funnel-grid">
                  <div className="metric-card">
                    <div className="metric-label">Unique Visitors</div>
                    <div className="metric-value">{funnel.unique_visitors}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Entry Sessions</div>
                    <div className="metric-value">{funnel.entry_sessions}</div>
                  </div>
                  {funnel.funnel.map((stage) => (
                    <div key={stage.stage} className="metric-card">
                      <div className="metric-label">{stage.stage}</div>
                      <div className="metric-value">{stage.count}</div>
                      <div className="metric-label dropoff-rate">Drop-off: {stage.dropoff_pct}%</div>
                    </div>
                  ))}
                  <div className="metric-card font-highlight">
                    <div className="metric-label font-bold">Funnel Conversion</div>
                    <div className="metric-value">{(funnel.conversion_rate * 100).toFixed(1)}%</div>
                  </div>
                </div>
              )}
            </section>

            <section className="heatmap-section">
              <h2>Zone Dwell Heatmap</h2>
              {heatmapData && <Heatmap data={heatmapData} />}
            </section>

            <section className="anomalies-section">
              <h2>Active Anomalies & Queue Alerts</h2>
              {anomalies.length === 0 ? (
                <div className="no-anomalies">✓ No store anomalies or queue spikes detected</div>
              ) : (
                <div className="anomalies-list">
                  {anomalies.map((anomaly, idx) => (
                    <div key={idx} className={`anomaly-card severity-${anomaly.severity.toLowerCase()}`}>
                      <div className="anomaly-header">
                        <span className="anomaly-type">{anomaly.type}</span>
                        <span className={`severity-tag tag-${anomaly.severity.toLowerCase()}`}>{anomaly.severity}</span>
                      </div>
                      <div className="anomaly-message">{anomaly.suggested_action}</div>
                      {anomaly.details && (
                        <div className="anomaly-details">
                          {Object.entries(anomaly.details).map(([k, v]) => (
                            <span key={k} className="detail-tag">{k}: {JSON.stringify(v)}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;

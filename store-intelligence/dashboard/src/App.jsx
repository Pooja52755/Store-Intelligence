import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import Heatmap from './Heatmap';

const apiHost = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
const apiBase = `http://${apiHost}:8000`;

function VisitorKnowledgeGraph({ journeys }) {
  if (!journeys || journeys.length === 0) return null;

  // Reconstruct nodes (unique zones) and edges
  const nodesSet = new Set();
  const edgeCounts = {};

  journeys.forEach(j => {
    const path = j.path;
    const frequency = j.frequency;

    path.forEach((zone, idx) => {
      nodesSet.add(zone);
      if (idx < path.length - 1) {
        const from = zone;
        const to = path[idx + 1];
        const key = `${from}->${to}`;
        edgeCounts[key] = (edgeCounts[key] || 0) + frequency;
      }
    });
  });

  const nodes = Array.from(nodesSet);
  const edges = Object.entries(edgeCounts).map(([key, count]) => {
    const [from, to] = key.split("->");
    return { from, to, count };
  });

  // Circular layout parameters
  const centerX = 250;
  const centerY = 180;
  const radius = 100;
  const nodePositions = {};

  nodes.forEach((node, idx) => {
    const angle = (idx / nodes.length) * 2 * Math.PI - Math.PI / 2;
    nodePositions[node] = {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
      label: node
    };
  });

  const maxCount = Math.max(...edges.map(e => e.count), 1);

  return (
    <div className="knowledge-graph-svg-container" style={{ display: 'flex', justifyContent: 'center', marginBottom: '20px' }}>
      <svg width="500" height="350" style={{ background: '#1e1e2e', borderRadius: '12px', border: '1px solid #313244', boxShadow: '0 4px 20px rgba(0,0,0,0.35)' }}>
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="22"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#b4befe" />
          </marker>
        </defs>

        {/* Draw Edges */}
        {edges.map((edge, idx) => {
          const fromPos = nodePositions[edge.from];
          const toPos = nodePositions[edge.to];
          if (!fromPos || !toPos) return null;

          const strokeWidth = Math.max(1.5, Math.min(6, (edge.count / maxCount) * 6));
          const opacity = Math.max(0.4, Math.min(0.9, edge.count / maxCount));

          return (
            <g key={`edge-${idx}`}>
              <line
                x1={fromPos.x}
                y1={fromPos.y}
                x2={toPos.x}
                y2={toPos.y}
                stroke="#b4befe"
                strokeWidth={strokeWidth}
                strokeOpacity={opacity}
                markerEnd="url(#arrowhead)"
              />
              <rect
                x={(fromPos.x + toPos.x) / 2 - 10}
                y={(fromPos.y + toPos.y) / 2 - 8}
                width="20"
                height="12"
                rx="3"
                fill="#1e1e2e"
              />
              <text
                x={(fromPos.x + toPos.x) / 2}
                y={(fromPos.y + toPos.y) / 2 + 1}
                fill="#a6adc8"
                fontSize="9"
                textAnchor="middle"
                fontWeight="bold"
              >
                {edge.count}
              </text>
            </g>
          );
        })}

        {/* Draw Nodes */}
        {nodes.map((node, idx) => {
          const pos = nodePositions[node];
          if (!pos) return null;

          return (
            <g key={`node-${idx}`} className="graph-node-group" style={{ cursor: 'pointer' }}>
              <circle
                cx={pos.x}
                cy={pos.y}
                r="15"
                fill="#313244"
                stroke="#b4befe"
                strokeWidth="2.5"
              />
              <text
                x={pos.x}
                y={pos.y + 4}
                fill="#ffffff"
                fontSize="10"
                textAnchor="middle"
                fontWeight="bold"
              >
                {node.charAt(0)}
              </text>
              <rect
                x={pos.x - 40}
                y={pos.y - 30}
                width="80"
                height="13"
                rx="3"
                fill="#11111b"
                fillOpacity="0.85"
                stroke="#313244"
                strokeWidth="0.5"
              />
              <text
                x={pos.x}
                y={pos.y - 20}
                fill="#cdd6f4"
                fontSize="8.5"
                textAnchor="middle"
                fontWeight="bold"
              >
                {pos.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function App() {
  const [storeId] = useState('STORE_BLR_002');
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [heatmapData, setHeatmapData] = useState(null);
  const [journeys, setJourneys] = useState([]);
  const [liveFrameSrc, setLiveFrameSrc] = useState('');
  const [liveFrameTime, setLiveFrameTime] = useState(Date.now());
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);

  const selectedRunIdRef = useRef(selectedRunId);
  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!liveFrameSrc) {
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }
    const img = new Image();
    img.onload = () => {
      if (canvas) {
        const ctx = canvas.getContext('2d');
        const targetWidth = img.naturalWidth || img.width || 640;
        const targetHeight = img.naturalHeight || img.height || 480;
        
        // Prevent clearing/flickering by only resizing the canvas if the dimensions actually change
        if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
          canvas.width = targetWidth;
          canvas.height = targetHeight;
        }
        
        ctx.drawImage(img, 0, 0, targetWidth, targetHeight);
      }
    };
    img.src = liveFrameSrc;
  }, [liveFrameSrc]);

  // Video Upload States
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [processingRunId, setProcessingRunId] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [processingError, setProcessingError] = useState(null);
  const [processingLogs, setProcessingLogs] = useState('');
  const [cameraId, setCameraId] = useState('CAM_UPLOAD');

  const processingRunIdRef = useRef(processingRunId);
  useEffect(() => {
    processingRunIdRef.current = processingRunId;
  }, [processingRunId]);

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
          if (!selectedRunIdRef.current) {
            setMetrics(data.metrics);
          }
        } else if (data.type === 'frame') {
          const activeRunId = selectedRunIdRef.current;
          const currentProcRunId = processingRunIdRef.current;
          
          if (currentProcRunId) {
            if (data.run_id === currentProcRunId) {
              setLiveFrameSrc(data.frame);
            }
          } else if (!activeRunId || data.run_id === activeRunId) {
            setLiveFrameSrc(data.frame);
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
  }, [storeId]);

  // Fetch available runs
  const fetchRuns = async () => {
    try {
      const response = await fetch(`${apiBase}/runs?store_id=${storeId}`);
      if (response.ok) {
        const data = await response.json();
        setRuns(data.runs || []);
        // Automatically default to the latest run if none selected
        if (!selectedRunIdRef.current && data.runs && data.runs.length > 0) {
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
  const fetchDashboardData = async (runId = null) => {
    const activeRunId = runId || selectedRunId;
    if (!activeRunId) return;
    
    try {
      const queryParams = `?run_id=${activeRunId}`;
      
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
      
      // Fetch journeys
      const jRes = await fetch(`${apiBase}/stores/${storeId}/journeys${queryParams}`);
      if (jRes.ok) {
        const jData = await jRes.json();
        setJourneys(jData.journeys || []);
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

  // Update liveFrameSrc on selectedRunId or processingRunId change for static frame
  useEffect(() => {
    if (!processingRunId && selectedRunId) {
      setLiveFrameSrc(`${apiBase}/stores/${storeId}/runs/${selectedRunId}/live-frame?t=${Date.now()}`);
    } else if (processingRunId) {
      setLiveFrameSrc('');
    } else {
      setLiveFrameSrc('');
    }
  }, [selectedRunId, processingRunId, storeId]);

  // Decoupled real-time dashboard analytics polling (every 1500ms)
  useEffect(() => {
    if (processingStatus === 'PROCESSING' && processingRunId) {
      const interval = setInterval(() => {
        fetchDashboardData(processingRunId);
      }, 1500);
      return () => clearInterval(interval);
    }
  }, [processingStatus, processingRunId]);

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
            await fetchRuns();
            setSelectedRunId(run.run_id);
            fetchDashboardData(run.run_id);
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
            {(selectedRunId || processingRunId) && (
              <section className="live-feed-section">
                <h2>Live CCTV YOLO Bounding Box Monitor</h2>
                <div className="live-feed-card">
                  <canvas 
                    ref={canvasRef} 
                    className="live-feed-image" 
                    style={{ display: liveFrameSrc ? 'block' : 'none' }}
                  />
                  {!liveFrameSrc && (
                    <img 
                      src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" 
                      alt="CCTV YOLO Feed Overlay" 
                      className="live-feed-image"
                    />
                  )}
                  {(processingStatus === 'PROCESSING' || processingRunId) && (
                    <div className="live-feed-overlay-text">
                      🔴 LIVE PROCESSING FEED
                    </div>
                  )}
                </div>
              </section>
            )}

            <section className="metrics-section">
              <h2>Retail Metrics Summary</h2>
              {metrics && (
                <div className="metrics-grid">
                  <div className="metric-card">

                    <div className="metric-label">Unique Customers</div>

                    <div className="metric-value">{metrics.unique_visitors}</div>

                  </div>

                  <div className="metric-card">

                    <div className="metric-label">Detected Staff</div>

                    <div className="metric-value">{metrics.unique_staff || 0}</div>

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

            <section className="journeys-section">
              <h2>Knowledge Graph: Common Visitor Pathways</h2>
              {journeys.length > 0 && <VisitorKnowledgeGraph journeys={journeys} />}
              {journeys.length === 0 ? (
                <div className="no-journeys">No journey pathways recorded for this run</div>
              ) : (
                <div className="journeys-list">
                  {journeys.map((j, idx) => (
                    <div key={idx} className="journey-card">
                      <div className="journey-freq-badge">
                        <strong>{j.frequency}</strong> {j.frequency === 1 ? 'visit' : 'visits'}
                      </div>
                      <div className="journey-flow">
                        {j.path.map((step, sIdx) => (
                          <React.Fragment key={sIdx}>
                            <span className={`journey-step step-${step.toLowerCase().replace(/ /g, '-')}`}>{step}</span>
                            {sIdx < j.path.length - 1 && <span className="journey-arrow">➔</span>}
                          </React.Fragment>
                        ))}
                      </div>
                    </div>
                  ))}
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
                  {anomalies.map((anomaly, idx) => {
                    const getAnomalyExplanation = (anom) => {
                      const details = anom.details || {};
                      switch (anom.type) {
                        case 'SUSPICIOUS_LOOP':
                          const loopPath = (details.pathway || []).map(z => z.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())).join(' ➔ ');
                          return `Visitor '${details.visitor_id}' has entered zone '${details.zone_id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}' non-consecutively ${details.visit_count} times in a looping path: ${loopPath}.`;
                        case 'BILLING_QUEUE_SPIKE':
                          return `Shopper checkout queue surged to ${details.queue_depth} visitors (system limit: ${details.threshold} people) for over ${details.duration_minutes} minutes.`;
                        case 'DEAD_ZONE':
                          const lastVisitStr = details.last_visit_timestamp === 'never' ? 'never during this run' : new Date(details.last_visit_timestamp).toLocaleTimeString();
                          return `Brand zone '${details.zone_id}' has recorded 0 shopper entries during this pipeline analysis (last visit: ${lastVisitStr}).`;
                        case 'CONVERSION_DROP':
                          return `Conversion rate dropped significantly to ${(details.today_rate * 100).toFixed(1)}% (7-day average: ${(details.avg_rate * 100).toFixed(1)}%, alert threshold: ${(details.threshold * 100).toFixed(1)}%).`;
                        case 'STALE_FEED':
                          return `Camera input stream has stalled. No new data packets received in the last ${Math.round(details.lag_seconds / 60)} minutes.`;
                        default:
                          return Object.entries(details).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(', ');
                      }
                    };

                    return (
                      <div key={idx} className={`anomaly-card severity-${anomaly.severity.toLowerCase()}`}>
                        <div className="anomaly-header">
                          <span className="anomaly-type-badge">{anomaly.type.replace(/_/g, ' ')}</span>
                          <span className={`severity-tag tag-${anomaly.severity.toLowerCase()}`}>{anomaly.severity}</span>
                        </div>
                        <div className="anomaly-message">
                          <strong>Suggested Action: </strong> {anomaly.suggested_action}
                        </div>
                        <div className="anomaly-explanation">
                          <strong>Retail Diagnostic: </strong> {getAnomalyExplanation(anomaly)}
                        </div>
                      </div>
                    );
                  })}
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

import React, { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, Legend, ResponsiveContainer } from 'recharts';

// Exact percentage centers computed from 1920x1080 store_layout.json coordinates
const ZONE_METADATA = {
  entry: { name: "Glass Door Entry", left: 14.3, top: 50 },
  backlit: { name: "Backlit Display", left: 3.9, top: 91.7 },
  nail_fragrance: { name: "Nail & Fragrance", left: 31.5, top: 45 },
  makeup_unit_center: { name: "Makeup stations (Center)", left: 54.1, top: 45 },
  central_aisle: { name: "FOH Central Aisle", left: 50.0, top: 50 },
  eb_zone: { name: "Salm / EB", left: 33.1, top: 7.0 },
  tfs_zone: { name: "The Face Shop", left: 42.0, top: 7.0 },
  good_vibes_zone: { name: "Good Vibes", left: 50.9, top: 7.0 },
  dermdoc_zone: { name: "DermDoc", left: 59.7, top: 7.0 },
  minimalist_zone: { name: "Minimalist", left: 68.6, top: 7.0 },
  aqualogica_zone: { name: "Aqualogica", left: 77.4, top: 7.0 },
  pilgrim_zone: { name: "Pilgrim / Foxtale", left: 86.3, top: 7.0 },
  dk_zone: { name: "D&K / JC", left: 95.3, top: 7.0 },
  maybelline_zone: { name: "Maybelline", left: 32.7, top: 88.0 },
  faces_zone: { name: "Faces Canada", left: 40.6, top: 88.0 },
  lakme_zone: { name: "Lakme", left: 48.5, top: 88.0 },
  mars_nybae_zone: { name: "Mars + Nybae", left: 56.5, top: 88.0 },
  mens_care_zone: { name: "Mens Care", left: 64.4, top: 88.0 },
  alps_loreal_zone: { name: "Alps / L'Oreal", left: 72.4, top: 88.0 },
  beauty_counter: { name: "Beauty counter", left: 80.3, top: 88.0 },
  cash_counter: { name: "Cash counter & checkout", left: 90.6, top: 45.0 },
  access: { name: "Staff Access", left: 92.1, top: 88.0 },
};

function Heatmap({ data }) {
  const [viewMode, setViewMode] = useState('floorplan'); // 'floorplan' or 'chart'
  const [hoveredZone, setHoveredZone] = useState(null);

  if (!data || !data.zones) {
    return <div className="no-data-card">No zone analysis data available</div>;
  }

  // Get color code based on score
  const getHotspotColor = (score) => {
    if (score >= 75) return 'rgba(239, 68, 68, 0.75)';   // Red/Hot (High dwell)
    if (score >= 45) return 'rgba(245, 158, 11, 0.75)';  // Amber/Warm (Medium dwell)
    if (score > 0) return 'rgba(59, 130, 246, 0.75)';    // Cyan/Cool (Low dwell)
    return 'rgba(107, 114, 128, 0.35)';                 // Grey/Cold
  };

  const getHotspotGlow = (score) => {
    if (score >= 75) return '0 0 20px rgba(239, 68, 68, 0.8)';
    if (score >= 45) return '0 0 15px rgba(245, 158, 11, 0.8)';
    if (score > 0) return '0 0 10px rgba(59, 130, 246, 0.8)';
    return 'none';
  };

  return (
    <div className="heatmap-card">
      <div className="heatmap-header">
        <div className="heatmap-title-desc">
          <p className="card-desc">Visualizing shopper metrics and engagement levels directly on Purplle's retail blueprint.</p>
        </div>
        <div className="view-toggle-container">
          <button 
            className={`toggle-btn ${viewMode === 'floorplan' ? 'active' : ''}`}
            onClick={() => setViewMode('floorplan')}
          >
            Blueprint Heatmap
          </button>
          <button 
            className={`toggle-btn ${viewMode === 'chart' ? 'active' : ''}`}
            onClick={() => setViewMode('chart')}
          >
            Statistical Chart
          </button>
        </div>
      </div>

      {viewMode === 'floorplan' ? (
        <div className="floorplan-map-wrapper">
          <div className="floorplan-container">
            <img 
              src="/floor_plan.png" 
              alt="Purplle Store Floor Plan" 
              className="floorplan-image"
            />
            
            {/* Interactive Pulse Hotspots */}
            {data.zones.map((zone) => {
              const meta = ZONE_METADATA[zone.zone_id];
              if (!meta) return null;

              const isHovered = hoveredZone && hoveredZone.zone_id === zone.zone_id;

              return (
                <div
                  key={zone.zone_id}
                  className={`hotspot-node ${zone.score >= 45 ? 'pulsing' : ''}`}
                  style={{
                    left: `${meta.left}%`,
                    top: `${meta.top}%`,
                    backgroundColor: getHotspotColor(zone.score),
                    boxShadow: getHotspotGlow(zone.score),
                  }}
                  onMouseEnter={() => setHoveredZone({ ...zone, ...meta })}
                  onMouseLeave={() => setHoveredZone(null)}
                >
                  <span className="hotspot-badge-inner"></span>
                </div>
              );
            })}

            {/* Highlighted YOLO Detection Points */}
            {data.detections && data.detections.map((det, idx) => {
              const leftPct = (det.x / 1920) * 100;
              const topPct = (det.y / 1080) * 100;
              
              if (leftPct < 0 || leftPct > 100 || topPct < 0 || topPct > 100) return null;

              return (
                <div
                  key={`det-${idx}`}
                  className="yolo-detection-node"
                  style={{
                    left: `${leftPct}%`,
                    top: `${topPct}%`,
                    position: 'absolute',
                    width: '7px',
                    height: '7px',
                    borderRadius: '50%',
                    backgroundColor: det.is_staff ? '#ff4b91' : '#00ffff',
                    boxShadow: det.is_staff ? '0 0 8px #ff4b91' : '0 0 8px #00ffff',
                    transform: 'translate(-50%, -50%)',
                    zIndex: 5,
                    pointerEvents: 'none'
                  }}
                />
              );
            })}

            {/* Premium Floating Tooltip */}
            {hoveredZone && (
              <div 
                className="floorplan-tooltip"
                style={{
                  left: `${hoveredZone.left > 75 ? hoveredZone.left - 20 : hoveredZone.left + 2}%`,
                  top: `${hoveredZone.top > 75 ? hoveredZone.top - 24 : hoveredZone.top + 2}%`,
                }}
              >
                <div className="tooltip-header">
                  <h4>{hoveredZone.name}</h4>
                  <span className="tooltip-zone-id">{hoveredZone.zone_id}</span>
                </div>
                <div className="tooltip-body">
                  <div className="tooltip-stat">
                    <span className="stat-name">Shopper Visits</span>
                    <span className="stat-val font-highlight">{hoveredZone.visit_count}</span>
                  </div>
                  <div className="tooltip-stat">
                    <span className="stat-name">Avg Dwell Duration</span>
                    <span className="stat-val font-highlight">{(hoveredZone.avg_dwell_ms / 1000).toFixed(1)}s</span>
                  </div>
                  <div className="tooltip-stat">
                    <span className="stat-name">Heat Score</span>
                    <span className="stat-val font-highlight">{hoveredZone.score.toFixed(0)}%</span>
                  </div>
                  <div className="tooltip-stat">
                    <span className="stat-name">Data Confidence</span>
                    <span className={`stat-val confidence-badge val-${hoveredZone.data_confidence.toLowerCase()}`}>
                      {hoveredZone.data_confidence}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
          
          {/* Map Legends */}
          <div className="floorplan-legend">
            <span className="legend-item"><span className="legend-dot color-hot"></span> High Engagement (&ge;75%)</span>
            <span className="legend-item"><span className="legend-dot color-warm"></span> Medium Dwell (&ge;45%)</span>
            <span className="legend-item"><span className="legend-dot color-cool"></span> Light Traffic (&gt;0%)</span>
            <span className="legend-item"><span className="legend-dot color-cold"></span> No Visits</span>
            <span className="legend-item"><span className="legend-dot" style={{ backgroundColor: '#00ffff', boxShadow: '0 0 6px #00ffff', display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', marginRight: '6px' }}></span> Shopper detection</span>
            <span className="legend-item"><span className="legend-dot" style={{ backgroundColor: '#ff4b91', boxShadow: '0 0 6px #ff4b91', display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', marginRight: '6px' }}></span> Staff detection</span>
          </div>
        </div>
      ) : (
        <div className="chart-view-wrapper">
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={data.zones} margin={{ top: 20, right: 30, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.07)" />
              <XAxis dataKey="zone_id" stroke="rgba(255,255,255,0.5)" tick={{ fontSize: 11 }} />
              <YAxis stroke="rgba(255,255,255,0.5)" />
              <ChartTooltip 
                contentStyle={{ background: 'rgba(30, 27, 46, 0.95)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '10px' }}
                itemStyle={{ color: '#fff' }}
                labelStyle={{ fontWeight: 'bold', color: '#a78bfa' }}
                formatter={(value, name) => {
                  if (name === 'visit_count') return [value, 'Visits'];
                  if (name === 'avg_dwell_ms') return [`${(value / 1000).toFixed(1)}s`, 'Avg Dwell'];
                  if (name === 'score') return [`${value.toFixed(0)}%`, 'Engagement Score'];
                  return [value, name];
                }}
              />
              <Legend wrapperStyle={{ paddingTop: 10 }} />
              <Bar dataKey="score" fill="#c084fc" radius={[4, 4, 0, 0]} name="score" />
              <Bar dataKey="visit_count" fill="#38bdf8" radius={[4, 4, 0, 0]} name="visit_count" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Grid Zone Stat Cards */}
      <div className="zone-stats-container">
        {data.zones.map((zone) => {
          const meta = ZONE_METADATA[zone.zone_id] || { name: zone.zone_id };
          return (
            <div key={zone.zone_id} className="zone-grid-card">
              <div className="zone-card-top">
                <h4>{meta.name}</h4>
                <span className={`confidence-pill pill-${zone.data_confidence.toLowerCase()}`}>
                  {zone.data_confidence}
                </span>
              </div>
              <div className="zone-card-metrics">
                <div className="zone-metric-row">
                  <span>Visits</span>
                  <span className="zone-metric-val">{zone.visit_count}</span>
                </div>
                <div className="zone-metric-row">
                  <span>Avg Dwell</span>
                  <span className="zone-metric-val">{(zone.avg_dwell_ms / 1000).toFixed(1)}s</span>
                </div>
                <div className="zone-metric-row">
                  <span>Engagement</span>
                  <span className="zone-metric-val weight-bold" style={{ color: getHotspotColor(zone.score) }}>
                    {zone.score.toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default Heatmap;

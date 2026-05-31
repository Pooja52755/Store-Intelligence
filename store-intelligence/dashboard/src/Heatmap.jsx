import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

function Heatmap({ data }) {
  if (!data || !data.zones) {
    return <div>No zone data available</div>;
  }

  return (
    <div className="heatmap-container">
      <ResponsiveContainer width="100%" height={400}>
        <BarChart data={data.zones}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="zone_id" />
          <YAxis />
          <Tooltip 
            formatter={(value, name) => {
              if (name === 'visit_count') return value;
              if (name === 'avg_dwell_ms') return `${(value / 1000).toFixed(1)}s`;
              if (name === 'score') return `${value.toFixed(0)}%`;
              return value;
            }}
          />
          <Legend />
          <Bar dataKey="score" fill="#8884d8" name="Heat Score" />
          <Bar dataKey="visit_count" fill="#82ca9d" name="Visits" />
        </BarChart>
      </ResponsiveContainer>

      <div className="zone-details">
        {data.zones.map((zone) => (
          <div key={zone.zone_id} className="zone-detail-card">
            <h3>{zone.zone_id}</h3>
            <p>Visits: {zone.visit_count}</p>
            <p>Avg Dwell: {(zone.avg_dwell_ms / 1000).toFixed(1)}s</p>
            <p>Heat Score: {zone.score.toFixed(0)}</p>
            <p className={`confidence ${zone.data_confidence.toLowerCase()}`}>
              Confidence: {zone.data_confidence}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default Heatmap;

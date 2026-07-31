import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { apiUrl } from '../apiBase';

function TokenStatusCard() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    axios.get(apiUrl('readiness'), { withCredentials: true })
      .then(response => {
        setStatus(response.data);
      })
      .catch(error => {
        console.error('Error fetching health status:', error);
      });
  }, []);

  return (
    <div className="bg-dark border-2 border-gold rounded-xl p-6 m-4 shadow-lg">
      <h2 className="text-2xl font-bold mb-4">🎯 Token Status</h2>
      {status ? (
        <div>
          <p>Access Token: {status.access_token_present ? '✅ Present' : '❌ Missing'}</p>
          <p>Instagram Account ID: {status.instagram_account_id_present ? '✅ Present' : '❌ Missing'}</p>
          <p>Status: {status.status}</p>
        </div>
      ) : (
        <p>Loading token status...</p>
      )}
    </div>
  );
}

export default TokenStatusCard;

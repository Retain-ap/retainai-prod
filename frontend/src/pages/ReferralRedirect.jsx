import React, { useEffect } from "react";
import { useParams } from "react-router";
import { apiUrl } from "../apiBase";

export default function ReferralRedirect() {
  const {code = ""} = useParams();
  const destination = /^[a-z0-9][a-z0-9-]{2,39}$/.test(code) ? apiUrl(`partners/r/${code}`) : "/partners";
  useEffect(() => { window.location.replace(destination); }, [destination]);
  return <main style={{padding: 32}}><p>Opening RetainAI…</p><a href={destination}>Continue</a></main>;
}

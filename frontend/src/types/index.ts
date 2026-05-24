// All TypeScript interfaces in one place — single source of truth

export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "procurement_manager" | "analyst";
  is_active: boolean;
}

export interface AuthState {
  accessToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  clearAuth: () => void;
}

export interface ParsedConstraints {
  category?: string;
  location_name?: string;
  location_lat?: number;
  location_lng?: number;
  location_radius_km?: number;
  certifications?: string[];
  capacity_min?: number;
  capacity_unit?: string;
  lead_time_max_days?: number;
}

export interface ComplianceMatrix {
  [constraint: string]: "PASS" | "FAIL" | "PARTIAL";
}

export interface QueryResult {
  rank: number;
  supplier_id: string;
  // Supplier details joined by the backend — avoids separate per-card fetch
  supplier_name?: string;
  supplier_city?: string;
  supplier_country?: string;
  supplier_lat?: number;
  supplier_lng?: number;
  supplier_certifications?: string[];
  supplier_capacity_value?: number;
  supplier_capacity_unit?: string;
  supplier_lead_time_days?: number;
  supplier_website?: string;
  // Scores
  total_score: number;
  constraint_score: number;
  semantic_score: number;
  proximity_score?: number;
  completeness_score: number;
  compliance_matrix: ComplianceMatrix;
  explanation: string;
  distance_km?: number;
}

export interface Supplier {
  id: string;
  name: string;
  description?: string;
  category?: string;
  country?: string;
  city?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  certifications?: string[];
  capacity_value?: number;
  capacity_unit?: string;
  lead_time_days?: number;
  website?: string;
  contact_email?: string;
  is_active: boolean;
  created_at: string;
}

export interface QueryWithResults {
  id: string;
  raw_query: string;
  status: "pending" | "processing" | "completed" | "failed";
  detected_language?: string;
  parsed_constraints?: ParsedConstraints;
  execution_time_ms?: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
  results: QueryResult[];
}

export interface AuditEntry {
  agent_name: string;
  action: string;
  reasoning?: string;
  input_snapshot?: { summary: string };
  output_snapshot?: { summary: string };
  duration_ms?: number;
  timestamp: string;
}

export interface SSEEvent {
  type: "connected" | "agent_update" | "complete" | "error";
  agent?: string;
  status?: string;
  message?: string;
  query_id?: string;
  result_count?: number;
  execution_time_ms?: number;
}

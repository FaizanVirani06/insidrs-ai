export type User = {
  user_id: number;
  username: string;
  role: "admin" | "showcase" | "user";
  is_admin?: boolean;
  is_showcase?: boolean;
  can_view_admin?: boolean;
  subscription_status?: string | null;
  stripe_customer_id?: string | null;
  current_period_end?: string | null;
  is_paid?: boolean;
};

export type TickerRow = {
  issuer_cik: string;
  current_ticker: string;
  issuer_name?: string | null;
  last_filing_date?: string | null;
  open_market_event_count?: number;
  ai_event_count?: number;
  best_event_ai_rating?: number | null;
  cluster_event_count?: number;
  market_cap?: number | null;
  market_cap_bucket?: string | null;
  market_cap_updated_at?: string | null;
  sector?: string | null;
  beta?: number | null;
};

export type UserProfilePreferences = {
  preferred_sectors: string[];
  min_ai_rating: number;
  max_beta: number | null;
  trade_side: "buy" | "sell" | "both";
  email_alerts_enabled: boolean;
  daily_digest_enabled: boolean;
  [k: string]: any;
};

export type UserProfileRecord = {
  user_id: number;
  full_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  preferences: UserProfilePreferences;
  created_at: string;
  updated_at: string;
};

export type InsiderEventRow = Record<string, any> & {
  issuer_cik: string;
  owner_key: string;
  accession_number: string;
  ticker?: string;
  filing_date?: string;
  event_trade_date?: string | null;
  owner_name_display?: string | null;
  owner_title?: string | null;
  is_officer?: number | null;
  is_director?: number | null;
  is_ten_percent_owner?: number | null;
  has_buy?: number;
  has_sell?: number;
  buy_dollars_total?: number | null;
  sell_dollars_total?: number | null;
  ai_buy_rating?: number | null;
  ai_sell_rating?: number | null;
  ai_confidence?: number | null;
  best_ai_rating?: number | null;
  cluster_flag_buy?: number | null;
  cluster_flag_sell?: number | null;
  market_cap?: number | null;
  market_cap_bucket?: string | null;
  sector?: string | null;
  beta?: number | null;
};

export type EventDetail = {
  event: InsiderEventRow;
  rows: any[];
  outcomes: any[];
  stats: any[];
  clusters: { buy: any | null; sell: any | null };
  ai_latest: any | null;
  trade_plan?: any | null;
};

export type PricePoint = { date: string; adj_close: number };

export type XPostChartPayload = {
  ticker: string;
  dates: string[];
  prices: number[];
  signal_date: string;
  signal_price: number;
  latest_price: number;
  return_pct: number;
};

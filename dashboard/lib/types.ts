export type Interaction = {
  type: string;
  at: string;
  q?: string; // only the newest items carry text
  a?: string;
};

export type DashboardData = {
  totalFarmers: number;
  totalInteractions: number;
  farmersWithLocation: number;
  crops: { crop: string; count: number }[];
  interactions: Interaction[];
};
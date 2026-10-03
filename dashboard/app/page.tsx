import { getData } from "../lib/stats";
import Dashboard from "../components/Dashboard";

export const revalidate = 60;
export const metadata = {
  title: "Gebere | An agronomist in every pocket",
  description: "Live, anonymized activity from Gebere, the AI farming assistant on Telegram.",
};

export default async function Home() {
  return <Dashboard data={await getData()} />;
}

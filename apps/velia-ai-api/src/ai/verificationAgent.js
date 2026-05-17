export const verificationAgent = {
  verify({ recommendation, logs = [], observations = [], userOverride = false }) {
    if (!logs.length && !observations.length) return { status: "no_confirmation", details: "No logged evidence" };
    if (userOverride) return { status: "partially_followed", details: "User override present" };
    if (recommendation.action === "irrigate" && logs.length) return { status: "followed", details: "Action logged" };
    if (observations[0]?.condition === "Looks too wet" && recommendation.action === "irrigate") return { status: "contradictory_observation", details: "Wet signal after irrigate recommendation" };
    return { status: "needs_follow_up", details: "Partial verification" };
  },
};

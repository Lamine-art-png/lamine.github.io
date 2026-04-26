export const verificationAgent = {
  verify({ recommendation, irrigationLogs = [], observations = [], userOverride = null }) {
    const latestLog = irrigationLogs[0];
    const latestObservation = observations[0];

    if (!latestLog && !latestObservation) {
      return { status: "no_confirmation", details: "No post-decision action logged yet." };
    }

    if (userOverride) {
      return { status: "partially_followed", details: "User override recorded." };
    }

    if (latestObservation?.condition === "Looks too wet" && recommendation.action === "irrigate") {
      return { status: "contradictory_observation", details: "Observation suggests overwatering risk." };
    }

    if (latestLog && recommendation.action === "irrigate") {
      return { status: "followed", details: "Irrigation log matches recommendation direction." };
    }

    return { status: "needs_follow_up", details: "Partial execution evidence only." };
  },
};

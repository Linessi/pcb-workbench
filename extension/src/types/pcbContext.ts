/** Board dimensions use the PCB SDK coordinate unit: mil. */
export interface PCBContext {
	projectName: string;
	board: {
		width: number;
		height: number;
		layers: string[];
	};
	components: Array<{
		reference: string;
		value: string;
		package: string;
	}>;
	nets: string[];
	statistics: {
		componentCount: number;
		netCount: number;
	};
}

export interface PCBPoint {
	x: number;
	y: number;
}

export type PCBComponent = PCBContext['components'][number];

export interface PCBComponentV2 extends PCBComponent {
	primitiveId?: string;
	x: number;
	y: number;
	rotation: number;
	layer: string;
}

export interface PCBPad extends PCBPoint {
	primitiveId?: string;
	component: string;
	number: string;
	net: string;
}

/** Shared net membership is a logical relation, not a routed copper path. */
export interface PCBConnection {
	source: string;
	target: string;
	net: string;
	basis: 'shared_net_name';
}

export interface PCBOutlinePrimitive {
	primitiveId: string;
	kind: 'polyline' | 'line' | 'arc';
	points?: PCBPoint[];
	/** Exact SDK polygon source when point discretization is unavailable. */
	source?: TPCB_PolygonSourceArray;
	arcAngle?: number;
}

export interface PCBHole extends PCBPoint {
	source: 'pad' | 'via';
	shape: 'round' | 'slot';
	width: number;
	height: number;
	component?: string;
	padNumber?: string;
}

export interface PCBVia extends PCBPoint {
	net: string;
	diameter: number;
	holeDiameter: number;
}

export interface PCBContextV2 extends PCBContext {
	schemaVersion: 2;
	components: PCBComponentV2[];
	pads: PCBPad[];
	connections: PCBConnection[];
	drc: {
		available: boolean;
		errors: string[];
		reason?: string;
		raw?: unknown;
		execution?: Record<string, unknown>;
	};
	provenance?: Record<string, unknown>;
	coverage?: Record<string, { status: 'available' | 'unavailable' | 'not_collected' | 'error'; reason_zh?: string }>;
	geometry: {
		outline: PCBOutlinePrimitive[];
		holes: PCBHole[];
		vias: PCBVia[];
	};
}


# coding: utf-8

# # Temp. diffusion & open SideWalls
# 
# ## Summary 
# 
# In this notebook we add temperature diffusion, and explore using different boundary conditions. Modelling temperature diffusion means we will now be evolving a mesh variable (temperatureField) rather than just advecting a swarm variable as in previous notebooks. This is prett simple, requiring that we:
# 
# * project the initial temperature structure (on the swarm var. ) onto the temperatureField mesh variable
# * create an advectionDiffusion  system with appropriate boundary conditions. 
# * connnect the bouyance force and rheology laws to the temperatureField rather than the swarm
# 
# 
# 
# 
# ## Dev Notes
# 
# 
# * If MOR lithostatic pressure tractions are applied at the sidewalls and bottom walls ($\sigma_{ij} \cdot n = 0$), the slab basically falls out the bottom. Once the slab leaves the bottom, the density dissapears, so $\vec{F}_{slab}$ reaches an equilibrium. Some trench advance occurs in the early part of the free sinking phase.  
# 
# * if only sidewalls are open, and the $\vec{V}_{x}$ is fixed to zero on a bottom edge node, the slab undergoes a significant trench advance in the early part of the free sinking phase. Is this an artifact of low resolution? Very much so. With higher resolution, the trench advance dissapears. The trench is then stationary until the salb encounters the lower mantle, after which a period of rollback occurs. However, the equilibrium dip appears to be vertical, and the trench tends to stationary. This appears to be true if we start with MORS at the sidewalls, or we simply have constant-width plates extending the sidewalls (like in Chertova)
# 
# 

# In[1]:


#!apt-cache policy petsc-dev


# In[2]:


#load in parent stuff
#%load_ext autoreload
import nb_load_stuff
from tectModelClass import *


# In[3]:


#If run through Docker we'll point at the local 'unsupported dir.'
#On hpc, the path should also include a directory holding the unsupported_dan.
import os
import sys

#this does't actually need to be protected. More a reminder it's an interim measure
try:
    sys.path.append('../../unsupported')
except:
    pass


# In[4]:


#%load_ext autoreload

#from unsupported_dan.UWsubduction.base_params import *
from unsupported_dan.UWsubduction.subduction_utils import *
from unsupported_dan.interfaces.marker2D import markerLine2D, line_collection
from unsupported_dan.interfaces.smoothing2D import *
from unsupported_dan.utilities.misc import cosine_taper


# In[5]:


#import dimensionless parameter dictionary
from unsupported_dan.UWsubduction.minimal_example import paramDict as ndp;
#import model settings dictionary
from unsupported_dan.UWsubduction.minimal_example import modelDict as md;
#import unit registry
from unsupported_dan.UWsubduction.minimal_example import u as uR;
#import the scaling module, importing from minimal_example  dimensionalization 
from unsupported_dan.UWsubduction.minimal_example import sub_scaling
from unsupported_dan.UWsubduction.minimal_example import rayleighNumber, stressScale, pressureDepthGrad
#stressScale = 1./sub_scaling.nonDimensionalize(1.*u.pascal)
ndimlz = sub_scaling.nonDimensionalize


# In[6]:


#print(ndp.surfaceTemp, ndp.surfaceTemp_)
#print(ndp.potentialTemp, ndp.potentialTemp_)
#rayleighNumber


# In[7]:


import numpy as np
import underworld as uw
from underworld import function as fn
import glucifer
from easydict import EasyDict as edict
import networkx as nx
import operator


# In[10]:


#md.faultDestroyDepth
#ndp.frictionMantle, ndp.frictionMantleDepth
#pressureDepthGrad


# ## Test - checking params

# In[9]:


#md.faultLocFac


# ## Changes to base params

# In[10]:


#These will keep changing if the notebook is run again without restarting!

#ndp.depth *= 0.9 #800 km
md.faultThickness *= 1.5 #15 km
md.res = 64

#ndp.interfaceViscCutoffDepth *= 1.2 #
#ndp.maxDepth *= 1.5

#ndp.radiusOfCurv*=0.6  #~300 km
#md.nltol = 0.025
#md.ppc = 40
#print(ndp.faultThickness*2900)
#ndp.yieldStressMax *=0.666  #150 Mpa
#md.buoyancyFac = 1.25
#md.refineMeshStatic = True
#ndp.leftLim = -3000./2900
#ndp.rightLim = 3000./2900
#md.druckerAlpha = 1.0
#ndp.faultCleanUpDepth = 500e3/sf.lengthScale


# In[11]:


#ndp.yieldStressMax*sf.stress
#dp.frictionMantle
#md.druckerAlpha
#dp.slabMaxAge


# ## Build mesh, Stokes Variables

# In[12]:


#1200.*2.5, ndp.leftLim*2900


# In[13]:


yres = int(md.res)
xres = int(md.res*6) 

halfWidth = 0.5*md.depth*md.aspectRatio 

if md.refineMesh:
    minCoord_    = (-1.*halfWidth, -1.*md.depth) 
    maxCoord_    = (halfWidth, 0.)
else:
    minCoord_    = (-1.*halfWidth, 1. - md.depth) 
    maxCoord_    = (halfWidth, 1.)

mesh = uw.mesh.FeMesh_Cartesian( elementType = (md.elementType),
                                 elementRes  = (xres, yres), 
                                 minCoord    = minCoord_, 
                                 maxCoord    = maxCoord_) 

velocityField = uw.mesh.MeshVariable( mesh=mesh,         nodeDofCount=2)
pressureField   = uw.mesh.MeshVariable( mesh=mesh.subMesh, nodeDofCount=1 )
temperatureField    = uw.mesh.MeshVariable( mesh=mesh,         nodeDofCount=1 )
temperatureDotField = uw.mesh.MeshVariable( mesh=mesh,         nodeDofCount=1 ) 
    

velocityField.data[:] = 0.
pressureField.data[:] = 0.
temperatureField.data[:] = 0.
temperatureDotField.data[:] = 0.


# In[14]:


meshLambda = 0.7
if md.refineMesh:

    mesh.reset()
    
    with mesh.deform_mesh():

        normXs = 2.*mesh.data[:,0]/(mesh.maxCoord[0] - mesh.minCoord[0])
        mesh.data[:,0] = mesh.data[:,0] * np.exp(meshLambda*normXs**2) / np.exp(meshLambda*1.0**2)

        normYs = -1.*mesh.data[:,1]/(mesh.maxCoord[1] - mesh.minCoord[1])
        mesh.data[:,1] = mesh.data[:,1] * np.exp(meshLambda*normYs**2)/np.exp(meshLambda*1.0**2)

        mesh.data[:,1] = mesh.data[:,1] + 1.0

    #Now we have to manuallt reset these attributes

    mesh._maxCoord = (mesh._maxCoord[0], 1.0)
    mesh._minCoord = (mesh._minCoord[0], 1.0 - md.depth)


# In[15]:


#figMesh = glucifer.Figure()
#figMesh.append( glucifer.objects.Mesh(mesh)) 
#figMesh.show()
#figMesh.save_database('test.gldb')


# In[16]:


#assert np.allclose(mesh.maxCoord[1], mesh.data[:,1].max())


# In[17]:


#wallYs = mesh.data[mesh.specialSets['MaxI_VertexSet'].data][:,1]
#dy1 = wallYs[-1] - wallYs[-2]


# In[18]:


#dy1/dy0


# ## Build plate model

# In[19]:


endTime = ndimlz(30*uR.megayear)
refVel = ndimlz(2*uR.cm/uR.year)
plateModelDt = ndimlz(0.1*uR.megayear)


# In[20]:


#Create tectonic model, add plates
tg = TectModel(mesh, 0, endTime, plateModelDt)
tg.add_plate(1, velocities=False)
tg.add_plate(2, velocities=False)

#add plate boundaries
tg.add_left_boundary(1, plateInitAge=0., velocities=False)
tg.add_subzone(1, 2, md.subZoneLoc, subInitAge=md.slabAge, upperInitAge=md.opAgeAtTrench)
tg.add_right_boundary(2, plateInitAge=0., velocities=False)


# ## Build plate age

# In[21]:


pIdFn = tg.plate_id_fn()
pAgeDict = tg.plate_age_fn() 

fnAge_map = fn.branching.map(fn_key = pIdFn , 
                          mapping = pAgeDict )

#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Surface(tg.mesh, fnAge_map ))
#fig.show()


# In[22]:


coordinate = fn.input()
depthFn = mesh.maxCoord[1] - coordinate[1]

platethickness = 2.32*fn.math.sqrt(1.*fnAge_map )  

halfSpaceTemp = ndp.potentialTemp_*fn.math.erf((depthFn)/(2.*fn.math.sqrt(1.*fnAge_map)))

plateTempProxFn = fn.branching.conditional( ((depthFn > platethickness, ndp.potentialTemp_ ), 
                                           (True,                      halfSpaceTemp)  ))



# In[23]:


#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Surface(tg.mesh, plateTempProxFn, onMesh = True))
#fig.show()


# ## Make swarm and Slabs

# In[24]:


def circGradientFn(S):
    if S == 0.:
        return 0.
    elif S < md.radiusOfCurv:
        return max(-S/np.sqrt((md.radiusOfCurv**2 - S**2)), -1e3)
    else:
        return -1e5
    
    
def linearGradientFn(S):
    return np.tan(np.deg2rad(-25.))


# In[25]:


swarm = uw.swarm.Swarm(mesh=mesh, particleEscape=True)
layout = uw.swarm.layouts.PerCellRandomLayout(swarm=swarm, particlesPerCell=int(md.ppc))
swarm.populate_using_layout( layout=layout ) # Now use it to populate.
proxyTempVariable = swarm.add_variable( dataType="double", count=1 )
proximityVariable      = swarm.add_variable( dataType="int", count=1 )
signedDistanceVariable = swarm.add_variable( dataType="double", count=1 )

#
proxyTempVariable.data[:] = 1.0
proximityVariable.data[:] = 0.0
signedDistanceVariable.data[:] = 0.0


# In[26]:


#All of these wil be needed by the slab / fault setup functions
#We have two main options, bind them to the TectModel class. 
#or provide them to the functions
#collection them in a dictionary may be a useful way too proviede them to the function 
#without blowing out the function arguments

tmUwMap = tm_uw_map([], velocityField, swarm, 
                    signedDistanceVariable, proxyTempVariable, proximityVariable)


# In[27]:


#define fault particle spacing, here ~5 paricles per element
ds = (tg.maxX - tg.minX)/(2.*tg.mesh.elementRes[0])

fCollection = line_collection([])



for e in tg.undirected.edges():
    if tg.is_subduction_boundary(e):
        build_slab_distance(tg, e, circGradientFn, md.slabInitMaxDepth, tmUwMap)        
        fb = build_fault(tg, e, circGradientFn, md.faultThickness , md.slabInitMaxDepth, ds, md.faultThickness, tmUwMap)
        fCollection.append(fb)

#
build_slab_temp(tmUwMap, ndp.potentialTemp_, md.slabAge)
fnJointTemp = fn.misc.min(proxyTempVariable,plateTempProxFn)

#And now reevaluate this guy on the swarm
proxyTempVariable.data[:] = fnJointTemp.evaluate(swarm)


# In[28]:


#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Points(swarm, proxyTempVariable))
#fig.show()
#fig.save_database('test.gldb')


# ## Temperature Field

# In[29]:


projectorMeshTemp= uw.utils.MeshVariable_Projection( temperatureField, proxyTempVariable , type=0 )
projectorMeshTemp.solve()



# In[52]:


#figTemp = glucifer.Figure()
#figTemp.append( glucifer.objects.Surface(mesh, temperatureField, onMesh=True, colourBar=False))
#figTemp.append( glucifer.objects.Contours(mesh, temperatureField,interval=0.33, 
#                                          colours='black', colourBar=False, quality=3))
#figTemp.show()
#figTemp.save_database('test.gldb')


# ##  Fault rebuild
# 
# In this sections we apply setup and apply some functions to help manage the spatial (spatial) distribution of faults, as velocity boundary conditions. Both objects need to be able to talk to teh TectModel.

# In[31]:


# Setup a swarm to define the replacment positions

fThick= fCollection[0].thickness

faultloc = 1. - md.faultThickness*md.faultLocFac

allxs = np.arange(mesh.minCoord[0], mesh.maxCoord[0], ds )[:-1]
allys = (mesh.maxCoord[1] - fThick)*np.ones(allxs.shape)

faultMasterSwarm = uw.swarm.Swarm( mesh=mesh )
dummy =  faultMasterSwarm.add_particles_with_coordinates(np.column_stack((allxs, allys)))
del allxs
del allys


# In[32]:


##What are we doing here??

#*faultRmfn descibs an area around the trench in which fault particles are allowed. Outside of this region they
#are destroyed using (remove_faults_from_boundaries). Note that the

#* faultAddFn desribes a region internal to the subduction plate wherwe we rebuild the fault. 
#this function deliberately'over-builds' the fault, while remove_faults_from_boundaries then trims it to size

#* velMaskFn defines the nodes where we will apply the plate velocties. 
#While leaving nodes near the plate boundaries free to adjust



faultRmfn = tg.t2f(tg.variable_boundary_mask_fn(distMax=10., distMin=ndimlz(10*uR.km), relativeWidth = 0.9, 
                                  minPlateLength =ndimlz(60*uR.km),  
                                           out = 'bool', boundtypes='sub' ))


#this one will put particles back into the fault
faultAddFn1 = tg.variable_boundary_mask_fn(distMax=10., distMin=ndimlz(10*uR.km), 
                                       relativeWidth = 0.95, minPlateLength =ndimlz(60*uR.km),  
                                           out = 'bool', boundtypes='sub' )

#thsi will keep the fault addition away from the subdcution zone
faultAddFn2 =  tg.t2f(tg.variable_boundary_mask_fn(distMax = ndimlz(150*uR.km), relativeWidth = 0.9 ))

faultAddFn = operator.and_( faultAddFn1 ,  faultAddFn2)






#order is very important here
dummy = remove_fault_drift(fCollection, faultloc)
dummy = pop_or_perish(tg, fCollection, faultMasterSwarm, faultAddFn , ds)
dummy = remove_faults_from_boundaries(tg, fCollection, faultRmfn )


# In[33]:


#maskFn_ = tg.t2f(faultRmfn)
#pIdFn = tg.plate_id_fn(maskFn=maskFn_)


# In[50]:


#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Surface(tg.mesh, faultAddFn, onMesh=True))
#fig.show()


# ## Fault rheology domain

# In[35]:


#xTfn = 
faultLength = ndimlz(300*uR.km)
faultTaper = ndimlz(300*uR.km)

subZoneDistfn = tg.subZoneAbsDistFn(upper=True)
faultTaperFunction  = cosine_taper(subZoneDistfn, faultLength, faultTaper)
depthTaperFn = cosine_taper(depthFn, md.interfaceViscCutoffDepth, md.interfaceViscEndWidth)


# In[60]:


#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Surface(tg.mesh, buoyancyMapFn[1] , onMesh = True))
#fig.show()


# ## Proximity
# 
# 

# In[61]:


proximityVariable.data[:] = 0


# In[62]:


for f in fCollection:
    f.rebuild()
    f.set_proximity_director(swarm, proximityVariable, searchFac = 2., locFac=1.0)


# In[39]:


#update_faults()


# In[46]:


#figProx = glucifer.Figure(figsize=(960,300) )
#figProx.append( glucifer.objects.Points(swarm , proximityVariable))
#figProx.append( glucifer.objects.Surface(mesh, faultRmfn))

#for f in fCollection:
#    figProx.append( glucifer.objects.Points(f.swarm, pointSize=5))

#figProx.show()


#figProx.save_database('test.gldb')


# In[41]:


#testMM = fn.view.min_max(uw.function.input(f.swarm.particleCoordinates))
#dummyFn = testMM.evaluate(tWalls)


# ## Boundary conditions

# In[42]:


appliedTractionField = uw.mesh.MeshVariable( mesh=mesh,    nodeDofCount=2 )


# In[43]:


iWalls = mesh.specialSets["MinI_VertexSet"] + mesh.specialSets["MaxI_VertexSet"]
jWalls = mesh.specialSets["MinJ_VertexSet"] + mesh.specialSets["MaxJ_VertexSet"]

tWalls = mesh.specialSets["MaxJ_VertexSet"]
bWalls = mesh.specialSets["MinJ_VertexSet"]
lWalls = mesh.specialSets["MinI_VertexSet"]
rWalls = mesh.specialSets["MaxI_VertexSet"]


# In[51]:


pressureGrad = fn.misc.constant(0.)

lithPressureFn = depthFn * pressureGrad


if lWalls.data.shape[0]:
    appliedTractionField.data[[lWalls.data]]=  np.column_stack((lithPressureFn.evaluate(lWalls), 
                                                            np.zeros(len(lWalls.data)) ))
if rWalls.data.shape[0]:
    appliedTractionField.data[[rWalls.data]]=  np.column_stack((-1*lithPressureFn.evaluate(rWalls), 
                                                            np.zeros(len(rWalls.data)) ))
#if bWalls.data.shape[0]:
#    appliedTractionField.data[[bWalls.data]]=  np.column_stack(( np.zeros(len(bWalls.data))  , 
#                                                            lithPressureFn.evaluate(bWalls) ) )


# In[52]:


vxId = bWalls & rWalls 
fixedVxNodes  = mesh.specialSets["Empty"]
fixedVxNodes  += vxId

#velBC = uw.conditions.DirichletCondition( variable      = velocityField, 
#                                               indexSetsPerDof = (iWalls , jWalls) )


########
#For open Sidewalls
########

velBC = uw.conditions.DirichletCondition( variable      = velocityField, 
                                               indexSetsPerDof = (fixedVxNodes, jWalls + iWalls) )

r_sub = rWalls - bWalls
b_sub = bWalls - rWalls

#note that b_sub is probably at the wrong loc herre, 
#though becase I'm applying zero tractions there is actually no difference. 
#nbc = uw.conditions.NeumannCondition( fn_flux=appliedTractionField, 
#                                      variable=velocityField,
#                                      indexSetsPerDof=(lWalls + b_sub + r_sub, None) )


nbc = uw.conditions.NeumannCondition( fn_flux=appliedTractionField, 
                                      variable=velocityField,
                                      indexSetsPerDof=(lWalls +  r_sub, None) )


# In[53]:


#Ridges Temp not enforced
dirichTempBC = uw.conditions.DirichletCondition(     variable=temperatureField, 
                                              indexSetsPerDof=(tWalls,) )

#Ridges enforced
#dirichTempBC = uw.conditions.DirichletCondition(     variable=temperatureField, 
#                                              indexSetsPerDof=(tWalls + iWalls,) )


###If we want thermal ridges fixed
#temperatureField.data[iWalls.data] = 1.


# ## Bouyancy

# In[53]:


# Now create a buoyancy force vector using the density and the vertical unit vector. 
#thermalDensityFn = ndp.rayleigh*(1. - proxyTempVariable)
thermalDensityFn = md.buoyancyFac*rayleighNumber*(1. - temperatureField)



gravity = ( 0.0, -1.0 )

buoyancyMapFn = thermalDensityFn*gravity


# In[55]:


#md.buoyancyFac*rayleighNumber*(1. - temperatureField)
#md.buoyancyFac


# ## Rheology

# In[73]:


symStrainrate = fn.tensor.symmetric( 
                            velocityField.fn_gradient )

#Set up any functions required by the rheology
strainRate_2ndInvariant = fn.tensor.second_invariant( 
                            fn.tensor.symmetric( 
                            velocityField.fn_gradient ))



def safe_visc(func, viscmin=md.viscosityMin, viscmax=md.viscosityMax):
    return fn.misc.max(viscmin, fn.misc.min(viscmax, func))


# In[74]:


#md.viscCombine


# temperatureFn = temperatureField
# 
# adiabaticCorrectFn = depthFn*ndp.tempGradMantle
# dynamicPressureProxyDepthFn = pressureField/sf.pressureDepthGrad
# druckerDepthFn = fn.misc.max(0.0, depthFn + md.druckerAlpha*(dynamicPressureProxyDepthFn))
# 
# #Diffusion Creep
# diffusionUM = (1./ndp.diffusionPreExp)*\
#             fn.math.exp( ((ndp.diffusionEnergy + (depthFn*ndp.diffusionVolume))/((temperatureFn+ adiabaticCorrectFn + ndp.surfaceTemp))))
# 
# diffusionLM = ndp.lowerMantleViscFac*(1./ndp.lowerMantlePreExp)*\
#             fn.math.exp( ((ndp.lowerMantleEnergy + (depthFn*ndp.lowerMantleVolume))/((temperatureFn+ adiabaticCorrectFn + ndp.surfaceTemp))))
# 
# viscosityLM = safe_visc(diffusionLM)
# 
# #Add non-linearity
# viscosityUM0 = safe_visc(diffusionUM)
# 
# if md.powerLaw:
#     powerLawSRFn= ((strainRate_2ndInvariant+ 1e-15)/ndp.powerLawStrain)**((1.-ndp.powerLawExp)/ndp.powerLawExp)
#     viscPower = viscosityUM0*powerLawSRFn
#     effviscosity = viscPower*viscosityUM0/(viscPower + viscosityUM0) #then combine harmonically
#     viscosityUM = safe_visc(effviscosity)
# 
# else:
#     viscosityUM = viscosityUM0
#     
# #combine upper an lower mantle   
# mantleCreep = fn.branching.conditional( ((depthFn < ndp.lowerMantleDepth, viscosityUM ), 
#                                            (True,                      diffusionLM )  ))
# 
# 
# #Define the mantle Plasticity
# ys =  ndp.cohesionMantle + (druckerDepthFn*ndp.frictionMantle)
# ysf = fn.misc.min(ys, ndp.yieldStressMax)
# yielding = ysf/(2.*(strainRate_2ndInvariant) + 1e-15) 
# 
# 
# if md.viscCombine == 0:
#     mantleRheologyFn = safe_visc(fn.misc.min(mantleCreep, yielding), viscmin=ndp.viscosityMin, viscmax=ndp.viscosityMax)
# else:
#     mantleRheologyFn =  safe_visc(mantleCreep*yielding/(mantleCreep + yielding), viscmin=ndp.viscosityMin, viscmax=ndp.viscosityMax)
#     
#     
# normDepths = depthFn/ndp.refDepthInterface
# interfaceCreep = ndp.refViscInterface*fn.math.exp(ndp.logDelVisc*(1. - normDepths) )
# #interfaceCreep = safe_visc(interfaceCreep0, viscmin=ndp.viscosityMinInterface, viscmax= ndp.viscosityMaxInterface)
# 
# #we want these avail. in all cases, as we evaluate it.
# #interfaceys =  ndp.cohesionInterface + (druckerFaultDepthFn*ndp.frictionInterface)
# #interfaceysf = fn.misc.min(interfaceys, ndp.ysMaxInterface)
# 
# 
# interfaceViscosityFn = 0.5
#     
# 
# #elif md.plasticInterface: #pseudo-brittle interface
# #    interfaceYielding = interfaceysf/(2.*(strainRate_2ndInvariant) + 1e-15)
# #    #combine
# #    interfaceViscosityFn = safe_visc(fn.misc.min(interfaceCreep , interfaceYielding), viscmin=ndp.viscosityMinInterface, viscmax=ndp.viscosityMaxInterface)
# 
# 
# #else: # a linear, brittle equivalent visc implementation
# #    ndp.effStrainRate = ndp.subVelocity/ndp.faultThickness
# #    effStressUpper =  ndp.cohesionInterface + (depthFn*ndp.frictionInterface)
# #    interfaceYielding = effStressUpper/(2.*ndp.effStrainRate)
# #    #combine
# #    interfaceViscosityFn = safe_visc(fn.misc.min(interfaceCreep , interfaceYielding), viscmin=ndp.viscosityMinInterface, viscmax=ndp.viscosityMaxInterface)
# 
# 
# 
# depthTaperFn = cosine_taper(depthFn, ndp.interfaceViscCutoffDepth, ndp.interfaceViscEndWidth)
# #interfaceRheologyFn =  interfaceViscosityFn*(1. - depthTaperFn) + depthTaperFn*mantleRheologyFn
# 
# interfaceRheologyFn =  interfaceViscosityFn*(1. - depthTaperFn) + depthTaperFn*mantleRheologyFn + faultTaperFunction*mantleRheologyFn,

# In[75]:



#fig = glucifer.Figure(figsize=(600, 300))
#fig.append( glucifer.objects.Surface(tg.mesh,depthTaperFn , onMesh = True))
#fig.show()


# In[65]:


#ndp.adiabaticTempGrad, ndp.surfaceTemp, ndp.diffusionVolumeDepth, md.druckerAlpha
#ndp.adiabaticTempGrad, pressureDepthGrad


# In[77]:


#use temperature field now
#temperatureFn = proxyTempVariable
temperatureFn = temperatureField


adiabaticCorrectFn = depthFn*ndp.adiabaticTempGrad
dynamicPressureProxyDepthFn = pressureField/pressureDepthGrad
druckerDepthFn = fn.misc.max(0.0, depthFn + md.druckerAlpha*(dynamicPressureProxyDepthFn))

#Diffusion Creep
diffusionUM = (1./ndp.diffusionPreExp)*    fn.math.exp( ((ndp.diffusionEnergyDepth + (depthFn*ndp.diffusionVolumeDepth))/((temperatureFn+ adiabaticCorrectFn + ndp.surfaceTemp))))

diffusionUM =     safe_visc(diffusionUM)
    
diffusionLM = md.lowerMantleViscFac*(1./ndp.diffusionPreExp)*    fn.math.exp( ((ndp.diffusionEnergyDepth + (depthFn*ndp.diffusionVolumeDepth))/((temperatureFn+ adiabaticCorrectFn + ndp.surfaceTemp))))

diffusionLM =     safe_visc(diffusionLM)

    
#combine upper and lower mantle   
mantleCreep = fn.branching.conditional( ((depthFn < md.lowerMantleDepth, diffusionUM ), 
                                           (True,                      diffusionLM )  ))

#Define the mantle Plasticity
ys =  ndp.cohesionMantle + (druckerDepthFn*ndp.frictionMantleDepth)
ysf = fn.misc.min(ys, md.yieldStressMax)
yielding = ysf/(2.*(strainRate_2ndInvariant) + 1e-15) 


#mantleRheologyFn = safe_visc(fn.misc.min(mantleCreep, yielding), viscmin=ndp.viscosityMin, viscmax=ndp.viscosityMax)
mantleRheologyFn =  safe_visc(mantleCreep*yielding/(mantleCreep + yielding), viscmin=md.viscosityMin, viscmax=md.viscosityMax)


#Subduction interface viscosity, comprosing bothe vertical and horizontal conditions
#interfaceRheologyFn= fn.branching.conditional( ((depthFn < ndp.lowerMantleDepth, fn.misc.constant(0.5) + faultTaperFunction*mantleRheologyFn), 
#                                           (depthFn > 2*ndp.faultThickness,                      fn.misc.constant(0.5))  ))


interfaceViscosityFn = ndp.viscosityInterface

interfaceRheologyFn =  interfaceViscosityFn*(1. - depthTaperFn) + depthTaperFn*mantleRheologyFn + faultTaperFunction*mantleRheologyFn


# In[78]:


#ndp.lowerMantleViscFac
md.viscosityMin, md.viscosityMax


# In[79]:


#viscconds = ((proximityVariable == 0, mantleRheologyFn),
#             (True, interfaceViscosityFn ))

#viscosityMapFn = fn.branching.conditional(viscconds)
#viscosityMapFn = mantleRheologyFn



viscosityMapFn = fn.branching.map( fn_key = proximityVariable,
                             mapping = {0:mantleRheologyFn,
                                        1:interfaceRheologyFn} )


# In[80]:


#viscosityMapFn.evaluate(swarm)
#mantleRheologyFn.evaluate(mesh)

#figV = glucifer.Figure(figsize=(960,300) )
#figV.append( glucifer.objects.Surface(mesh, buoyancyMapFn[1], onMesh=True))
#figV.show()


# ## Stokes

# In[81]:


surfaceArea = uw.utils.Integral(fn=1.0,mesh=mesh, integrationType='surface', surfaceIndexSet=tWalls)
surfacePressureIntegral = uw.utils.Integral(fn=pressureField, mesh=mesh, integrationType='surface', surfaceIndexSet=tWalls)

NodePressure = uw.mesh.MeshVariable(mesh, nodeDofCount=1)
Cell2Nodes = uw.utils.MeshVariable_Projection(NodePressure, pressureField, type=0)
Nodes2Cell = uw.utils.MeshVariable_Projection(pressureField, NodePressure, type=0)

def smooth_pressure(mesh):
    # Smooths the pressure field.
    # Assuming that pressure lies on the submesh, do a cell -> nodes -> cell
    # projection.

    Cell2Nodes.solve()
    Nodes2Cell.solve()

# a callback function to calibrate the pressure - will pass to solver later
def pressure_calibrate():
    (area,) = surfaceArea.evaluate()
    (p0,) = surfacePressureIntegral.evaluate()
    offset = p0/area
    pressureField.data[:] -= offset
    smooth_pressure(mesh)


# In[82]:


stokes = uw.systems.Stokes( velocityField  = velocityField, 
                                   pressureField  = pressureField,
                                   conditions     = [velBC, nbc],
                                   #conditions     = [velBC, ],
                                   fn_viscosity   = viscosityMapFn, 
                                   fn_bodyforce   = buoyancyMapFn )


# In[83]:


solver = uw.systems.Solver(stokes)

solver.set_inner_method("mumps")
solver.options.scr.ksp_type="cg"
solver.set_penalty(1.0e7)
solver.options.scr.ksp_rtol = 1.0e-4


# In[84]:


solver.solve(nonLinearIterate=True, nonLinearTolerance=md.nltol, callback_post_solve = pressure_calibrate)
solver.print_stats()


# ## Advection - Diffusion

# In[85]:


advDiff = uw.systems.AdvectionDiffusion( phiField       = temperatureFn, 
                                         phiDotField    = temperatureDotField, 
                                         velocityField  = velocityField,
                                         fn_sourceTerm    = 0.0,
                                         fn_diffusivity = 1., 
                                         #conditions     = [neumannTempBC, dirichTempBC] )
                                         conditions     = [ dirichTempBC] )


# ## Swarm Advector

# In[86]:


advector = uw.systems.SwarmAdvector( swarm=swarm, velocityField=velocityField, order=2 )


# In[87]:


population_control = uw.swarm.PopulationControl(swarm, deleteThreshold=0.006, 
                                                splitThreshold=0.25,maxDeletions=1, maxSplits=3, aggressive=True,
                                                aggressiveThreshold=0.9, particlesPerCell=int(md.ppc))


# ## Update functions

# In[88]:


# Here we'll handle everything that should be advected - i.e. every timestep
def advect_update(dt):
    # Retrieve the maximum possible timestep for the advection system.
    #dt = advector.get_max_dt()
    # Advect swarm
    advector.integrate(dt)
    
    #Advect faults
    for f in fCollection:
        f.advection(dt)
    
    
    return time+dt, step+1


# In[89]:


#velocityField.data[:] = 0.
#pressureField.data[:] = 0.
#ndp.interfaceViscEndWidth*2900


# In[ ]:





# In[90]:


def update_faults():
    
    ##the mask fns are static at this stage
    #ridgeMaskFn = tg.ridge_mask_fn(ridgedist)
    #subMaskFn = tg.subduction_mask_fn(subdist)
    #boundMaskFn = tg.combine_mask_fn(ridgeMaskFn , subMaskFn )
    
    
    
    #order is very important here
    dummy = remove_fault_drift(fCollection, faultloc)
    dummy = pop_or_perish(tg, fCollection, faultMasterSwarm, faultAddFn , ds)
    dummy = remove_faults_from_boundaries(tg, fCollection, faultRmfn )
    
    for f in fCollection:
        
        #Remove particles below a specified depth
        depthMask = f.swarm.particleCoordinates.data[:,1] <         (1. - md.faultDestroyDepth)
        with f.swarm.deform_swarm():
            f.swarm.particleCoordinates.data[depthMask] = (9999999., 9999999.)
        
        #Here we're grabbing a 'black box' routine , 
        #which is supposed to maintain particle density and smooth
        #quite experimental!!!
        repair_markerLines(f, ds, k=8)
    
#faultRmfn


# In[91]:


def update_swarm():
    
    
    
    for f in fCollection:
        f.rebuild()
        f.set_proximity_director(swarm, proximityVariable, searchFac = 2., locFac=1.0,
                                maxDistanceFn=fn.misc.constant(2.))
        
    #A simple depth cutoff for proximity
    depthMask = swarm.particleCoordinates.data[:,1] < (1. - md.faultDestroyDepth)
    proximityVariable.data[depthMask] = 0
    


# In[92]:


outputPath = os.path.join(os.path.abspath("."),"output/files")

if uw.rank()==0:
    if not os.path.exists(outputPath):
        os.makedirs(outputPath)
uw.barrier()


#surfacexs = mesh.data[tWalls.data][:,0]
#surfaceys = mesh.data[tWalls.data][:,1]
#surfLine = markerLine2D(mesh, velocityField,surfacexs, surfaceys , 0,  99)
#surfVx = uw.swarm.SwarmVariable(surfLine.swarm, 'double', 1)

#def save_files(step):
#    surfVx.data[:] = velocityField[0].evaluate(surfLine.swarm)
    
#    surfVx.save( "output/files/surfVx_" + str(step).zfill(3) + "_.h5")


# In[93]:


#save_files(0)


# In[94]:


#e = (3,3)
#time = 1e-5
#for e in tg.undirected.edges():
#    print(tg.bound_has_vel(e, time))


# In[106]:


#dp.refLength


# In[108]:


def set_boundary_vel_update(tectModel, platePair, time, dt):
    bv = 0.
    try:
        bv = tectModel.bound_velocity(platePair, time=time)
    except:
        pass
    
    dx = bv*dt
    newx = (tectModel.get_bound_loc(platePair) + dx)
    
    return newx


def strain_rate_field_update(tectModel, e, tmUwMap):
    dist = ndimlz(100*uR.kilometer) #limit the search radius
    maskFn = tectModel.plate_boundary_mask_fn(dist, out='num',bound=e )
    srLocMins, srLocMaxs = strain_rate_min_max(tectModel, tmUwMap, maskFn)
    if tg.is_subduction_boundary(e):
        return srLocMins[0][1]
    else:
        return srLocMaxs[0][1]
    

def update_tect_model(tectModel, tmUwMap, time, dt = 0.0 ):
    
    """
    An example of how we can update the tect_model
    """
    for e in tectModel.undirected.edges():
        
        #This is generally the first condition to check" a specified boundary velocity
        if tectModel.bound_has_vel(e, time):
            newX = set_boundary_vel_update(tectModel, e, time, dt)
            tectModel.set_bound_loc(e, newX)
            
        #in this model the ficticious boundaries remain fixed at the edge
        elif e[0] == e[1]:
            pass       
        #now we'll apply a strain rate query to update the subduction zone loc
        elif tectModel.is_subduction_boundary(e):
            e = tectModel.subduction_edge_order(e)
            newx = strain_rate_field_update(tectModel, e, tmUwMap)
            tectModel.set_bound_loc(e, newx)
        else:
            pass
        


def rebuild_mask_fns():

    faultRmfn = tg.t2f(tg.variable_boundary_mask_fn(distMax=10., distMin=ndimlz(10*uR.kilometer), relativeWidth = 0.9, 
                                      minPlateLength =ndimlz(60*uR.kilometer),  
                                               out = 'bool', boundtypes='sub' ))


    #this one will put particles back into the fault
    faultAddFn1 = tg.variable_boundary_mask_fn(distMax=10., distMin=ndimlz(10*uR.kilometer), 
                                           relativeWidth = 0.95, minPlateLength =ndimlz(60*uR.kilometer),  
                                               out = 'bool', boundtypes='sub' )

    faultAddFn2 =  tg.t2f(tg.variable_boundary_mask_fn(distMax = ndimlz(100*uR.kilometer), relativeWidth = 0.9 ))


    faultAddFn = operator.and_( faultAddFn1 ,  faultAddFn2)



    
    
    #the following dictates where the fault rheology will be activated
    subZoneDistfn = tg.subZoneAbsDistFn(upper=True)
    faultTaperFunction  = cosine_taper(subZoneDistfn, faultLength, faultTaper)
    
    return faultRmfn, faultAddFn, faultTaperFunction
    
    


# ## Track the values of the plate bounaries

# In[96]:


valuesDict = edict({})
valuesDict.timeAtSave = []
valuesDict.stepAtSave = []
for e in tg.undirected.edges():
    valuesDict[str(e)] = []
valuesDict    


# In[97]:


def valuesUpdateFn():
    
    """ 
    Assumes global variables:
    * time
    * step 
    ...
    + many functions
    """
    
    
    #save the time and step
    valuesDict.timeAtSave.append(time) 
    valuesDict.stepAtSave.append(step)
    
    for e in tg.undirected.edges():
        if tg.is_subduction_boundary(e):
            ee = tg.subduction_edge_order(e) #hacky workaround for the directed/ undireted. need get_bound_loc
        else:
            ee = e

        valuesDict[str(e)].append(tg.get_bound_loc(ee))
        
        
    #save
    if uw.rank()==0:
        fullpath = os.path.join(outputPath + "tect_model_data")
        #the '**' is important
        np.savez(fullpath, **valuesDict)
    


# In[98]:


#valuesUpdateFn()
#valuesDict  
#!ls output


# 
# ## Viz

# In[99]:


outputPath = os.path.join(os.path.abspath("."),"output/")


if uw.rank()==0:
    if not os.path.exists(outputPath):
        os.makedirs(outputPath)
uw.barrier()


# In[100]:


viscSwarmVar =  swarm.add_variable( dataType="double", count=1 )
viscSwarmVar.data[:] = viscosityMapFn.evaluate(swarm)


# In[101]:


store1 = glucifer.Store('output/subduction1')
store2 = glucifer.Store('output/subduction2')
store3 = glucifer.Store('output/subduction3')
store4 = glucifer.Store('output/subduction4')


figTemp = glucifer.Figure(store1, figsize=(960,300) )
figTemp.append( glucifer.objects.Surface(mesh, temperatureField, onMesh=True))
figTemp.append( glucifer.objects.Contours(mesh, temperatureField, interval=0.2,  colours='Black', colourBar=False))          

figVisc = glucifer.Figure( store2, figsize=(960,300) )
#figVisc.append( glucifer.objects.Points(swarm, viscosityMapFn, pointSize=2, logScale=True) )
figVisc.append( glucifer.objects.Points(swarm,  viscSwarmVar, logScale=True) )



figVel = glucifer.Figure( store3, figsize=(960,300) )
figVel.append(glucifer.objects.Surface(mesh, fn.math.dot(velocityField, velocityField), onMesh=True))
figVel.append( glucifer.objects.VectorArrows(mesh, velocityField, arrowHead=0.2, scaling=1./refVel) )

figProx = glucifer.Figure(store4, figsize=(960,300) )
figProx.append( glucifer.objects.Points(swarm , proximityVariable))
for f in fCollection:
    figProx.append( glucifer.objects.Points(f.swarm, pointSize=5))


#figMask.append( glucifer.objects.Surface(mesh,  maskFnVar3) )
for f in fCollection:
    figVel.append( glucifer.objects.Points(f.swarm, pointSize=5))



# In[102]:


#figTemp.show()
#figVisc.save_database('test.gldb')


# In[103]:


#1e-2*2900.


# ## Main Loop

# In[104]:


time = 0.  # Initial time
step = 0 
maxSteps = 1000      # Maximum timesteps 
steps_output = 5   # output every N timesteps
swarm_update = 5   # output every N timesteps
faults_update = 5
dt_model = 0.
steps_update_model = 5

valuesUpdateFn()


# In[110]:


#step


# In[111]:


#while time < tg.times[-1]:
while step < maxSteps:
    # Solve non linear Stokes system
    solver.solve(nonLinearIterate=True, nonLinearTolerance=md.nltol, callback_post_solve = pressure_calibrate)

    
    #
    dt = advDiff.get_max_dt()
    advDiff.integrate(dt)
    
    #advect swarm and faults
    time, step =  advect_update(dt)
    dt_model += dt
    
    
    
        
    #update tectonic model
    if step % steps_update_model == 0:
        update_tect_model(tg, tmUwMap, time, dt = dt_model)
        dt_model = 0.
        #ridgeMaskFn, subMaskFn, boundMaskFn, pIdFn= rebuild_mask_fns()
        plate_id_fn = tg.plate_id_fn()
        faultRmfn, faultAddFn, faultTaperFunction = rebuild_mask_fns()
        
        #these need to be explicity updated
        #interfaceViscosityFn = fn.misc.constant(0.5) + faultTaperFunction*mantleRheologyFn
        interfaceRheologyFn =  interfaceViscosityFn*(1. - depthTaperFn) + depthTaperFn*mantleRheologyFn + faultTaperFunction*mantleRheologyFn
        
        viscosityMapFn = fn.branching.map( fn_key = proximityVariable,
                             mapping = {0:mantleRheologyFn,
                                        1:interfaceRheologyFn} )
        #also update this guy for viz
        viscSwarmVar.data[:] = viscosityMapFn.evaluate(swarm)
        valuesUpdateFn()
        
    #running fault healing/addition, map back to swarm
    if step % faults_update == 0:
        update_faults()
    if step % swarm_update == 0:
        population_control.repopulate()
        update_swarm()
        
        
    #rebuild stokes
    #if step % steps_update_model == 0:
    #    del solver
    #    del stokes
    #    stokes = update_stokes(time, viscosityMapFn )
    #    solver = rebuild_solver(stokes)
        
    
    # output figure to file at intervals = steps_output
    if step % steps_output == 0 or step == maxSteps-1:
        #Important to set the timestep for the store object here or will overwrite previous step
        store1.step = step
        store2.step = step
        store3.step = step
        store4.step = step
        
        figTemp.save(    outputPath + "temp"    + str(step).zfill(4))
        figVisc.save(    outputPath + "visc"    + str(step).zfill(4))
        figVel.save(    outputPath + "vel"    + str(step).zfill(4))
        figProx.save(    outputPath + "prox"    + str(step).zfill(4))
        #save out the surface velocity
        #save_files(step)
    
    if uw.rank()==0:
        print 'step = {0:6d}; time = {1:.3e}'.format(step,time)
